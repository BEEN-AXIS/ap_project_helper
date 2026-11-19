"""The Runner interface and the data that flows through the judge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class TestCase:
    __test__ = False  # not a pytest class
    index: int
    input: str
    expected: str | None  # absent for custom runs
    is_sample: bool = False


@dataclass
class Limits:
    time_ms: int
    wall_ms: int
    memory_mb: int
    output_kb: int
    fsize_bytes: int
    nofile: int = 64
    nproc: int = 64
    stderr_tail_kb: int = 4

    def to_json(self) -> dict[str, int]:
        return self.__dict__.copy()


@dataclass
class Job:
    language: str
    source: str
    tests: list[TestCase]
    mode: Literal["samples", "full", "custom"]
    stop_on_first_fail: bool
    limits: Limits
    run_argv: list[str]
    file: str = "main.py"
    checker: str = "exact"
    checker_script: str | None = None


@dataclass
class TestVerdict:
    __test__ = False  # not a pytest class
    index: int
    code: str  # AC, WA, TLE, MLE, RE, OLE (OK for custom runs)
    time_ms: int
    memory_kb: int
    stdout_tail: str | None = None  # samples and custom runs only
    stderr_tail: str | None = None


@dataclass
class JobResult:
    compile_error: str | None
    verdicts: list[TestVerdict] = field(default_factory=list)
    system_error: bool = False
    system_message: str = ""

    def summary(self, total: int) -> tuple[str, int | None, int]:
        """(verdict code, failed test number (1-based) or None, tests passed)."""
        if self.system_error:
            return "SE", None, 0
        if self.compile_error is not None:
            return "CE", None, 0
        passed = 0
        for v in self.verdicts:
            if v.code in ("AC", "OK"):
                passed += 1
                continue
            return v.code, v.index + 1, passed
        if passed < total:
            return "SE", None, passed
        return ("AC" if total else "SE"), None, passed


ProgressFn = Callable[[TestVerdict], Awaitable[None]]


@dataclass
class RunnerHealth:
    ok: bool
    name: str
    sandboxed: bool
    detail: str = ""


class Runner(Protocol):
    name: str
    sandboxed: bool

    async def healthcheck(self) -> RunnerHealth: ...

    async def run(self, job: Job, on_progress: ProgressFn) -> JobResult: ...


async def no_progress(_v: TestVerdict) -> None:
    return None
