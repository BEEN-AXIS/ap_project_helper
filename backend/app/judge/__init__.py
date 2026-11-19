"""Judge: runner selection and job building."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.domain.gameconfig import GameConfig
from app.judge.runner import Job, Limits, Runner, TestCase

log = logging.getLogger("algoarena.judge")


def make_runner(settings: Settings) -> Runner:
    backend = settings.judge_backend
    if backend == "fake" or (backend == "auto" and settings.env == "test"):
        from app.judge.fake_runner import FakeRunner

        return FakeRunner(settings.env)
    if backend == "judge0":
        from app.judge.judge0_runner import Judge0Runner

        return Judge0Runner(settings.judge0_url)
    if backend in ("docker", "auto"):
        from app.judge.docker_runner import DockerRunner, docker_available, docker_image_present

        if backend == "docker":
            return DockerRunner(settings.judge_image)
        if docker_available() and docker_image_present(settings.judge_image):
            return DockerRunner(settings.judge_image)
        if settings.is_prod:
            raise RuntimeError(
                f"JUDGE_BACKEND=auto found no Docker judge image {settings.judge_image!r}; "
                "run `make judge-image` or set JUDGE_BACKEND=judge0"
            )
        log.warning("Docker or the judge image is missing; using the DEV SANDBOX subprocess runner "
                    "(run `make judge-image` to judge in containers)")
    from app.judge.subprocess_runner import SubprocessRunner

    return SubprocessRunner(settings.env)


def build_limits(time_limit_ms: int, memory_mb: int, lang_mult: int, cfg: GameConfig, cap_ms: int | None = None) -> Limits:
    j = cfg.judge
    t = time_limit_ms * lang_mult
    if cap_ms is not None:
        t = min(t, cap_ms)
    return Limits(
        time_ms=t,
        wall_ms=j.wall_factor * t + j.wall_extra_ms,
        memory_mb=memory_mb,
        output_kb=j.output_limit_kb,
        fsize_bytes=j.dev_fsize_mb * 1024 * 1024,
        nofile=64,
        nproc=j.max_processes,
        stderr_tail_kb=j.stderr_tail_kb,
    )


def build_job(
    *,
    cfg: GameConfig,
    language: str,
    source: str,
    tests: list[TestCase],
    mode: str,
    time_limit_ms: int,
    memory_mb: int,
    checker: str,
    checker_script: str | None = None,
) -> Job:
    lang = cfg.language(language)
    cap = cfg.judge.run_time_cap_ms if mode in ("samples", "custom") else None
    return Job(
        language=language,
        source=source,
        tests=tests,
        mode=mode,  # type: ignore[arg-type]
        stop_on_first_fail=cfg.judge.stop_on_first_fail if mode == "full" else False,
        limits=build_limits(time_limit_ms, memory_mb, lang.time_multiplier, cfg, cap),
        run_argv=lang.run.split(),
        file=lang.file,
        checker=checker,
        checker_script=checker_script,
    )
