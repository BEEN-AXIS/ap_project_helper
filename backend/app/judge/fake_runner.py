"""FakeRunner: exists only when ENV=test. Simulated, never runs code.

The verdict comes from a marker comment in the submitted code, which makes
end-to-end tests and the five-minute demo deterministic:

    # VERDICT: AC          every test passes
    # VERDICT: WA 3        wrong answer on test 3 (also TLE, MLE, RE, OLE)
    # VERDICT: CE          compile error
    # VERDICT: SE          judge system error (no recoil)
    # DELAY_MS: 400        simulated judging time per test (default 60)

Code without a marker is treated as AC.
"""

from __future__ import annotations

import asyncio
import re

from app.judge.runner import Job, JobResult, ProgressFn, RunnerHealth, TestVerdict

_VERDICT = re.compile(r"#\s*VERDICT:\s*(AC|WA|TLE|MLE|RE|OLE|CE|SE)(?:\s+(\d+))?", re.I)
_DELAY = re.compile(r"#\s*DELAY_MS:\s*(\d+)", re.I)


class FakeRunner:
    name = "fake"
    sandboxed = False

    def __init__(self, env: str) -> None:
        if env != "test":
            raise RuntimeError("FakeRunner is only available with ENV=test")

    async def healthcheck(self) -> RunnerHealth:
        return RunnerHealth(True, self.name, False, "simulated verdicts (ENV=test)")

    async def run(self, job: Job, on_progress: ProgressFn) -> JobResult:
        m = _VERDICT.search(job.source)
        code = (m.group(1).upper() if m else "AC")
        fail_at = int(m.group(2)) if m and m.group(2) else 1
        d = _DELAY.search(job.source)
        delay = (int(d.group(1)) if d else 60) / 1000
        if code == "CE":
            await asyncio.sleep(delay)
            return JobResult(compile_error="line 1: invalid syntax (simulated)")
        if code == "SE":
            await asyncio.sleep(delay)
            return JobResult(compile_error=None, system_error=True, system_message="simulated system error")
        result = JobResult(compile_error=None)
        for t in job.tests:
            await asyncio.sleep(delay)
            failing = code != "AC" and t.index + 1 >= fail_at
            vcode = code if failing else ("OK" if t.expected is None else "AC")
            show = job.mode in ("samples", "custom")
            out = (t.expected or "") if not failing else "simulated wrong output\n"
            v = TestVerdict(t.index, vcode, 12, 9000, out if show else None, None)
            result.verdicts.append(v)
            await on_progress(v)
            if failing and job.stop_on_first_fail:
                break
        return result
