"""Run (free) and Submit (the attack) on top of the judge pool."""

from __future__ import annotations

from app.core.errors import AppError
from app.domain.gameconfig import GameConfig
from app.judge import build_job, language_tools_present
from app.judge.pool import PRIORITY_PRACTICE, PRIORITY_RUN, PRIORITY_SUBMIT, JudgePool
from app.judge.runner import JobResult, ProgressFn, TestCase, no_progress
from app.services.problems import CachedProblem


def validate_code(code: str, cfg: GameConfig) -> None:
    if not code.strip():
        raise AppError("empty_code", "Write some code first")
    if len(code.encode()) > cfg.match.max_code_bytes:
        raise AppError("code_too_large", "Code must be under 64 KB")


def validate_language(language: str, cfg: GameConfig, runner_name: str | None = None) -> None:
    try:
        lang = cfg.language(language)
    except KeyError:
        raise AppError("validation", f"Unknown language {language!r}") from None
    if runner_name and not language_tools_present(cfg, runner_name).get(language, True):
        tool = (lang.compile or lang.run).split()[0]
        raise AppError(
            "validation",
            f"{lang.name} is not available on this server: {tool} was not found. "
            "Install it (on a Mac: xcode-select --install) or judge in Docker (make judge-image).",
        )


async def run_samples(
    pool: JudgePool, cfg: GameConfig, problem: CachedProblem, language: str, code: str,
    custom_input: str | None, practice: bool = False,
) -> dict:
    """A free Run: the sample tests, or one custom input. Never touches HP."""
    validate_language(language, cfg, pool.runner.name)
    validate_code(code, cfg)
    if custom_input is not None:
        if len(custom_input.encode()) > cfg.judge.custom_input_limit_kb * 1024:
            raise AppError("validation", "Custom input must be under 64 KB")
        tests = [TestCase(0, custom_input, None, True)]
        mode = "custom"
    else:
        tests = problem.samples
        mode = "samples"
    job = build_job(cfg=cfg, language=language, source=code, tests=tests, mode=mode, time_limit_ms=problem.time_limit_ms,
                    memory_mb=problem.memory_mb, checker=problem.checker, checker_script=problem.checker_script)
    res = await pool.submit(job, PRIORITY_PRACTICE if practice else PRIORITY_RUN)
    verdict, failed, passed = res.summary(len(tests))
    by_index = {t.index: t for t in tests}
    return {
        "mode": mode,
        "verdict": "OK" if (mode == "custom" and verdict == "AC") else verdict,
        "failed_test": failed,
        "passed": passed,
        "total": len(tests),
        "compile_error": res.compile_error,
        "system_error": res.system_error,
        "time_cap_ms": job.limits.time_ms,
        "tests": [
            {
                "index": v.index, "code": v.code, "time_ms": v.time_ms, "memory_kb": v.memory_kb,
                "input": by_index[v.index].input, "expected": by_index[v.index].expected,
                "output": v.stdout_tail, "stderr": v.stderr_tail,
            }
            for v in res.verdicts
        ],
    }


async def judge_full(
    pool: JudgePool, cfg: GameConfig, problem: CachedProblem, language: str, code: str,
    on_progress: ProgressFn = no_progress,
) -> tuple[JobResult, int]:
    """Submit: every test, samples first, stopping at the first failure."""
    tests = problem.all_tests
    job = build_job(cfg=cfg, language=language, source=code, tests=tests, mode="full", time_limit_ms=problem.time_limit_ms,
                    memory_mb=problem.memory_mb, checker=problem.checker, checker_script=problem.checker_script)
    return await pool.submit(job, PRIORITY_SUBMIT, on_progress), len(tests)
