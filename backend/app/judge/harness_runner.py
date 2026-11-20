"""Shared logic for runners that drive harness/run_tests.py and read its JSON lines.

The harness never sees expected outputs. This side compares each test's
stdout with the problem's checker and turns harness statuses into verdicts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from pathlib import Path

from app.judge import checkers
from app.judge.runner import Job, JobResult, ProgressFn, TestVerdict

HARNESS_DIR = Path(__file__).resolve().parent / "harness"
log = logging.getLogger("algoarena.judge")


def harness_spec(job: Job) -> dict:
    return {
        "language": job.language,
        "file": job.file,
        "source": job.source,
        "run": job.run_argv,
        "compile": job.compile_argv,
        "compile_limits": {"cpu_s": job.compile_time_s, "memory_mb": job.compile_memory_mb},
        "limits": job.limits.to_json(),
        "stop_on_first_fail": job.stop_on_first_fail,
        "tests": [{"index": t.index, "input": t.input} for t in job.tests],
    }


def to_verdict(job: Job, line: dict) -> TestVerdict:
    test = next(t for t in job.tests if t.index == line["index"])
    status = line["status"]
    stdout = line.get("stdout", "")
    if status == "OK":
        if test.expected is None:
            code = "OK"
        else:
            ok = checkers.check(job.checker, test.expected, stdout, test.input, job.checker_script)
            code = "AC" if ok else "WA"
    else:
        code = status
    show_output = job.mode in ("samples", "custom")
    return TestVerdict(
        index=test.index,
        code=code,
        time_ms=int(line.get("time_ms", 0)),
        memory_kb=int(line.get("memory_kb", 0)),
        stdout_tail=stdout if show_output else None,
        stderr_tail=(line.get("stderr_tail") or None) if show_output else None,
    )


async def drive_harness(
    argv: list[str], job: Job, on_progress: ProgressFn, cwd: str | None, env: dict[str, str]
) -> JobResult:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
        limit=8 * 1024 * 1024,
    )
    result = JobResult(compile_error=None)
    assert proc.stdin and proc.stdout and proc.stderr
    try:
        proc.stdin.write(json.dumps(harness_spec(job)).encode())
        await proc.stdin.drain()
        proc.stdin.close()
        done = False
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            msg = json.loads(raw)
            if msg["type"] == "compile_error":
                result.compile_error = msg["message"]
            elif msg["type"] == "system_error":
                result.system_error = True
                result.system_message = msg["message"]
                done = True
                break
            elif msg["type"] == "test":
                v = to_verdict(job, msg)
                result.verdicts.append(v)
                await on_progress(v)
                if job.stop_on_first_fail and v.code not in ("AC", "OK"):
                    break
            elif msg["type"] == "done":
                done = True
                break
        if not done and result.compile_error is None and not (
            result.verdicts and job.stop_on_first_fail and result.verdicts[-1].code not in ("AC", "OK")
        ):
            err = (await proc.stderr.read()).decode(errors="replace")[-2000:]
            log.warning("harness ended early", extra={"fields": {"stderr": err[-500:]}})
            result.system_error = True
            result.system_message = "judge harness ended unexpectedly"
        return result
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)
