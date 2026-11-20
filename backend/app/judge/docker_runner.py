"""DockerRunner: the default when a Docker daemon is reachable.

One container per job (not per test). The harness and the language runtime
live in a slim image (Dockerfile.judge). The job spec, including the source,
goes in on stdin, so nothing from the host is mounted. Flags follow section 11
of the build brief. Docker socket access is root on the host: in compose the
API never gets the socket; a separate judge-worker service does.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid

from app.judge.harness_runner import drive_harness
from app.judge.runner import Job, JobResult, ProgressFn, RunnerHealth


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    sock = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    if sock.startswith("unix://"):
        return os.path.exists(sock[len("unix://"):]) or os.path.exists(os.path.expanduser("~/.docker/run/docker.sock"))
    return True


def docker_image_present(image: str) -> bool:
    """True when the daemon answers and the judge image is built (make judge-image)."""
    import subprocess

    try:
        r = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


class DockerRunner:
    name = "docker"
    sandboxed = True

    def __init__(self, image: str) -> None:
        self.image = image

    async def healthcheck(self) -> RunnerHealth:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "image", "inspect", self.image,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await asyncio.wait_for(proc.wait(), 10)
        except Exception as e:  # pragma: no cover
            return RunnerHealth(False, self.name, True, f"docker unavailable: {e}")
        if rc != 0:
            return RunnerHealth(False, self.name, True, f"image {self.image} missing: run make judge-image")
        return RunnerHealth(True, self.name, True, self.image)

    def argv(self, job: Job, name: str) -> list[str]:
        lim = job.limits
        # Compilers need far more memory than the program they build; the program's
        # own cap is still the RLIMIT_AS (and RSS polling) the harness applies per test.
        mem = lim.memory_mb + 128 if not job.compile_argv else max(lim.memory_mb, job.compile_memory_mb) + 128
        return [
            "docker", "run", "--rm", "-i", "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,size=64m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(lim.nproc),
            # Headroom over the per-test limit for the harness itself; the user
            # program's own cap is the RLIMIT_AS set by limit_exec.py.
            "--memory", f"{mem}m",
            "--memory-swap", f"{mem}m",
            "--cpus", "1",
            "--user", "65534:65534",
            "--ulimit", f"nofile={lim.nofile}",
            "-w", "/tmp",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            self.image,
            "python3", "-I", "/harness/run_tests.py",
        ]

    async def run(self, job: Job, on_progress: ProgressFn) -> JobResult:
        name = f"aa-job-{uuid.uuid4().hex[:12]}"
        try:
            return await drive_harness(self.argv(job, name), job, on_progress, None, dict(os.environ))
        finally:
            # --rm removes it on exit; this covers a cancelled or killed client.
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
