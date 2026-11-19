"""Bounded judge worker pool.

JUDGE_CONCURRENCY workers pull jobs in priority order: match submits first,
then Runs, then practice. At most max_queued jobs wait; beyond that callers
get `busy`. A job that waits longer than queue_timeout_s, overruns
job_timeout_s, or hits a runner failure returns a system error (no recoil).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from dataclasses import dataclass, field

from app.core.errors import AppError
from app.judge.runner import Job, JobResult, ProgressFn, Runner, no_progress

log = logging.getLogger("algoarena.judge")

PRIORITY_SUBMIT = 0
PRIORITY_RUN = 1
PRIORITY_PRACTICE = 2


@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    enqueued: float = field(compare=False)
    job: Job = field(compare=False)
    on_progress: ProgressFn = field(compare=False)
    future: asyncio.Future = field(compare=False)  # type: ignore[type-arg]


@dataclass
class PoolMetrics:
    jobs: int = 0
    system_errors: int = 0
    last_wait_ms: int = 0
    total_wait_ms: int = 0
    total_run_ms: int = 0

    def snapshot(self, queued: int) -> dict[str, float]:
        n = max(1, self.jobs)
        return {
            "queued": queued, "jobs": self.jobs, "system_errors": self.system_errors,
            "avg_wait_ms": round(self.total_wait_ms / n, 1), "avg_run_ms": round(self.total_run_ms / n, 1),
        }


class JudgePool:
    def __init__(self, runner: Runner, concurrency: int, max_queued: int, queue_timeout_s: float, job_timeout_s: float):
        self.runner = runner
        self.concurrency = max(1, concurrency)
        self.max_queued = max_queued
        self.queue_timeout_s = queue_timeout_s
        self.job_timeout_s = job_timeout_s
        self._queue: asyncio.PriorityQueue[_Item] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._seq = itertools.count()
        self.metrics = PoolMetrics()
        self._active = 0

    async def start(self) -> None:
        if self._workers:
            return
        self._queue = asyncio.PriorityQueue()
        self._workers = [asyncio.create_task(self._worker(i), name=f"judge-{i}") for i in range(self.concurrency)]

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await w
        self._workers = []

    @property
    def queued(self) -> int:
        return self._queue.qsize() if self._queue else 0

    @property
    def idle(self) -> bool:
        return self.queued == 0 and self._active == 0

    async def submit(self, job: Job, priority: int, on_progress: ProgressFn = no_progress) -> JobResult:
        if self._queue is None:
            await self.start()
        assert self._queue is not None
        if self._queue.qsize() >= self.max_queued:
            raise AppError("busy", "The judge queue is full, try again shortly")
        fut: asyncio.Future[JobResult] = asyncio.get_running_loop().create_future()
        await self._queue.put(_Item(priority, next(self._seq), time.monotonic(), job, on_progress, fut))
        return await fut

    async def _worker(self, _i: int) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            self._active += 1
            try:
                waited = time.monotonic() - item.enqueued
                self.metrics.last_wait_ms = int(waited * 1000)
                self.metrics.total_wait_ms += int(waited * 1000)
                if waited > self.queue_timeout_s:
                    res = JobResult(compile_error=None, system_error=True, system_message="judge queue timeout")
                else:
                    t0 = time.monotonic()
                    try:
                        res = await asyncio.wait_for(self.runner.run(item.job, item.on_progress), self.job_timeout_s)
                    except TimeoutError:
                        res = JobResult(compile_error=None, system_error=True, system_message="judge job timeout")
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # runner failure: void, no recoil
                        log.exception("runner failure", exc_info=e)
                        res = JobResult(compile_error=None, system_error=True, system_message="judge runner failure")
                    self.metrics.total_run_ms += int((time.monotonic() - t0) * 1000)
                self.metrics.jobs += 1
                if res.system_error:
                    self.metrics.system_errors += 1
                if not item.future.done():
                    item.future.set_result(res)
            finally:
                self._active -= 1
                self._queue.task_done()
