"""Checkers (golden vectors), the shared harness through the dev runner, and the pool."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import SHARED_DIR, load_game_config_file
from app.judge import build_job, checkers
from app.judge.fake_runner import FakeRunner
from app.judge.pool import JudgePool
from app.judge.runner import JobResult, TestCase, TestVerdict
from app.judge.subprocess_runner import SubprocessRunner, tripwire

CFG = load_game_config_file()
CASES = json.loads((SHARED_DIR / "golden" / "checkers.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['checker']}-{c['pass']}-{c['actual'][:8]!r}")
def test_checker_vectors(case: dict) -> None:
    assert checkers.check(case["checker"], case["expected"], case["actual"]) is case["pass"]


def test_custom_checker_script() -> None:
    script = "import sys\nexp=open(sys.argv[2]).read().split(); out=open(sys.argv[3]).read().split()\nsys.exit(0 if sorted(exp)==sorted(out) else 1)\n"
    assert checkers.check("custom", "1 2 3", "3 1 2", "", script)
    assert not checkers.check("custom", "1 2 3", "3 1 1", "", script)


def test_summary_logic() -> None:
    v = lambda i, c: TestVerdict(i, c, 1, 1)  # noqa: E731
    assert JobResult(None, [v(0, "AC"), v(1, "AC")]).summary(2) == ("AC", None, 2)
    assert JobResult(None, [v(0, "AC"), v(1, "WA")]).summary(3) == ("WA", 2, 1)
    assert JobResult("line 1: bad", []).summary(3) == ("CE", None, 0)
    assert JobResult(None, [], system_error=True).summary(3) == ("SE", None, 0)
    assert JobResult(None, [v(0, "AC")]).summary(3) == ("SE", None, 1)  # missing results are never a pass


def test_tripwire_is_only_a_tripwire() -> None:
    assert tripwire("import subprocess") and tripwire("from socket import socket") and tripwire("import os\nos.system('x')")
    assert tripwire("import sys\ninput = sys.stdin.readline") is None
    assert tripwire("import os\ndata = os.read(0, 10)") is None


def test_fake_runner_refuses_outside_test() -> None:
    with pytest.raises(RuntimeError):
        FakeRunner("dev")
    with pytest.raises(RuntimeError):
        SubprocessRunner("prod")


def _job(src: str, tests: list[TestCase], mode: str = "full", tl: int = 2000):  # type: ignore[no-untyped-def]
    return build_job(cfg=CFG, language="python", source=src, tests=tests, mode=mode, time_limit_ms=tl, memory_mb=256, checker="exact")


@pytest.mark.anyio
async def test_input_is_fed_on_stdin_and_hidden_outputs_never_leave() -> None:
    r = SubprocessRunner("test")
    tests = [TestCase(0, "2 3\n", "5\n", True), TestCase(1, "10 20\n", "30\n", False)]
    src = "a, b = map(int, input().split())\nprint(a + b)\n"
    full = await r.run(_job(src, tests), lambda v: asyncio.sleep(0))
    assert full.summary(2) == ("AC", None, 2)
    assert all(v.stdout_tail is None and v.stderr_tail is None for v in full.verdicts)  # full mode: no outputs
    samples = await r.run(_job(src, tests[:1], "samples"), lambda v: asyncio.sleep(0))
    assert samples.verdicts[0].stdout_tail == "5\n"


@pytest.mark.anyio
async def test_stop_on_first_fail_and_progress_streams() -> None:
    r = SubprocessRunner("test")
    tests = [TestCase(i, f"{i}\n", f"{i}\n", False) for i in range(5)]
    seen: list[str] = []

    async def prog(v: TestVerdict) -> None:
        seen.append(v.code)

    res = await r.run(_job("x = int(input())\nprint(x if x < 2 else -1)\n", tests), prog)
    assert res.summary(5) == ("WA", 3, 2)
    assert seen == ["AC", "AC", "WA"]


@pytest.mark.anyio
async def test_pool_orders_and_reports_busy_and_timeouts() -> None:
    class Slow:
        name, sandboxed = "slow", False

        async def healthcheck(self):  # type: ignore[no-untyped-def]
            return None

        async def run(self, job, on_progress):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.3)
            return JobResult(None, [TestVerdict(0, "AC", 1, 1)])

    pool = JudgePool(Slow(), concurrency=1, max_queued=1, queue_timeout_s=0.1, job_timeout_s=0.2)
    await pool.start()
    job = _job("print(1)", [TestCase(0, "", "1\n")])
    t1 = asyncio.create_task(pool.submit(job, 0))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(pool.submit(job, 0))
    await asyncio.sleep(0.01)
    from app.core.errors import AppError

    with pytest.raises(AppError) as e:
        await pool.submit(job, 0)
    assert e.value.code == "busy"
    r1, r2 = await t1, await t2
    assert r1.system_error and r1.system_message == "judge job timeout"
    assert r2.system_error and r2.system_message == "judge queue timeout"
    await pool.stop()
