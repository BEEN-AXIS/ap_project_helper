"""Judge0Runner (optional): calls a self-hosted Judge0 CE through JUDGE0_URL.

For hosts that cannot start sibling containers (Render, Railway). Each test is
one Judge0 submission in a batch; results are polled. Not exercised by the
test suite in this repository (no Judge0 instance available here).
"""

from __future__ import annotations

import asyncio
import base64

from app.judge import checkers
from app.judge.runner import Job, JobResult, ProgressFn, RunnerHealth, TestVerdict

LANGUAGE_IDS = {"python": 71, "cpp": 54}  # Judge0 CE: Python 3.8.1, C++ (GCC 9.2.0); config judge0_id wins
STATUS = {3: "OK", 4: "WA", 5: "TLE", 6: "CE", 7: "RE", 8: "RE", 9: "RE", 10: "RE", 11: "RE", 12: "RE", 13: "SE", 14: "SE"}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _unb64(s: str | None) -> str:
    return base64.b64decode(s).decode(errors="replace") if s else ""


class Judge0Runner:
    name = "judge0"
    sandboxed = True

    def __init__(self, url: str) -> None:
        if not url:
            raise RuntimeError("JUDGE0_URL is not set")
        self.url = url.rstrip("/")

    async def healthcheck(self) -> RunnerHealth:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.url}/about")
            return RunnerHealth(r.status_code == 200, self.name, True, self.url)
        except Exception as e:
            return RunnerHealth(False, self.name, True, str(e))

    async def run(self, job: Job, on_progress: ProgressFn) -> JobResult:
        import httpx

        lang = job.judge0_id or LANGUAGE_IDS.get(job.language)
        if lang is None:
            return JobResult(compile_error=None, system_error=True, system_message="language not mapped for Judge0")
        lim = job.limits
        subs = [
            {
                "language_id": lang, "source_code": _b64(job.source), "stdin": _b64(t.input),
                "cpu_time_limit": lim.time_ms / 1000, "wall_time_limit": lim.wall_ms / 1000,
                "memory_limit": lim.memory_mb * 1024, "enable_network": False,
            }
            for t in job.tests
        ]
        result = JobResult(compile_error=None)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.url}/submissions/batch?base64_encoded=true", json={"submissions": subs})
            r.raise_for_status()
            tokens = [x["token"] for x in r.json()]
            for t, token in zip(job.tests, tokens, strict=True):
                while True:
                    g = await c.get(f"{self.url}/submissions/{token}?base64_encoded=true")
                    data = g.json()
                    if data["status"]["id"] > 2:
                        break
                    await asyncio.sleep(0.25)
                code = STATUS.get(data["status"]["id"], "SE")
                if code == "CE":
                    result.compile_error = _unb64(data.get("compile_output"))[:2000]
                    return result
                if code == "SE":
                    result.system_error = True
                    return result
                out = _unb64(data.get("stdout"))
                if code == "OK":
                    code = "OK" if t.expected is None else ("AC" if checkers.check(job.checker, t.expected, out, t.input) else "WA")
                show = job.mode in ("samples", "custom")
                v = TestVerdict(t.index, code, int(float(data.get("time") or 0) * 1000), int(data.get("memory") or 0),
                                out if show else None, _unb64(data.get("stderr"))[-4096:] if show else None)
                result.verdicts.append(v)
                await on_progress(v)
                if job.stop_on_first_fail and code not in ("AC", "OK"):
                    break
        return result
