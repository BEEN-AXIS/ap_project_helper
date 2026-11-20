"""SubprocessRunner: DEVELOPMENT ONLY. Not a security boundary.

Runs the shared harness as a child process in a fresh temporary directory
with a stripped environment, rlimits set by limit_exec.py, a killed process
group on timeout, capped output and (on macOS, where RLIMIT_AS is ignored)
resident-memory polling. It cannot stop network access or reads of files the
server user can read. The lobby and editor show a "DEV SANDBOX" badge while
it is active, and it refuses to start when ENV=prod.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import shutil
import sys
import tempfile

from app.judge.harness_runner import HARNESS_DIR, drive_harness
from app.judge.runner import Job, JobResult, ProgressFn, RunnerHealth

log = logging.getLogger("algoarena.judge")

# A tripwire, not security: blocks the obvious, nothing more.
TRIPWIRE_MODULES = {"subprocess", "socket", "ctypes", "multiprocessing", "pty", "shutil", "signal", "resource"}
TRIPWIRE_OS_CALLS = {"system", "popen", "fork", "forkpty", "kill", "killpg", "remove", "unlink", "rmdir",
                     "removedirs", "rename", "execv", "execve", "execvp", "execl", "spawnv", "setsid"}


def tripwire(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None  # the harness reports the compile error
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in TRIPWIRE_MODULES:
                    return f"import of {a.name} is not allowed in the dev sandbox"
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in TRIPWIRE_MODULES:
                return f"import of {node.module} is not allowed in the dev sandbox"
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            if node.attr in TRIPWIRE_OS_CALLS or node.attr.startswith("exec") or node.attr.startswith("spawn"):
                return f"os.{node.attr} is not allowed in the dev sandbox"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            return "__import__ is not allowed in the dev sandbox"
    return None


# The same idea for C++: process control, shells and sockets.
_CPP_TRIPWIRE = re.compile(
    r"\b(system|popen|fork|vfork|execv|execve|execvp|execl|execlp|posix_spawn|kill|socket|connect|remove|unlink|rename)\s*\("
    r"|#\s*include\s*<\s*(unistd\.h|sys/socket\.h|sys/wait\.h|spawn\.h|netinet/in\.h|arpa/inet\.h|dlfcn\.h)\s*>"
)


def cpp_tripwire(source: str) -> str | None:
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S)  # ignore comments
    m = _CPP_TRIPWIRE.search(code)
    if not m:
        return None
    what = m.group(1) or f"<{m.group(2)}>"
    return f"{what} is not allowed in the dev sandbox"


class SubprocessRunner:
    name = "subprocess"
    sandboxed = False

    def __init__(self, env: str = "dev", use_tripwire: bool = True) -> None:
        if env == "prod":
            raise RuntimeError("SubprocessRunner is development-only and refuses to start with ENV=prod")
        self.use_tripwire = use_tripwire
        log.warning("DEV SANDBOX: the subprocess judge runner is not safe for untrusted users")

    async def healthcheck(self) -> RunnerHealth:
        return RunnerHealth(True, self.name, False, "dev sandbox: not safe for untrusted users")

    async def run(self, job: Job, on_progress: ProgressFn) -> JobResult:
        if self.use_tripwire:
            reason = tripwire(job.source) if job.language == "python" else cpp_tripwire(job.source) if job.language == "cpp" else None
            if reason:
                return JobResult(compile_error=f"DEV SANDBOX tripwire: {reason}")
        workdir = tempfile.mkdtemp(prefix="aa-job-")
        os.chmod(workdir, 0o700)
        try:
            argv = [sys.executable, "-I", str(HARNESS_DIR / "run_tests.py")]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            job = _with_interpreter(job)
            return await drive_harness(argv, job, on_progress, workdir, env)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _with_interpreter(job: Job) -> Job:
    """Run Python with the server's own interpreter rather than whatever python3 is on PATH."""
    if job.language == "python" and job.run_argv and job.run_argv[0] in ("python3", "python"):
        from dataclasses import replace

        return replace(job, run_argv=[sys.executable, *job.run_argv[1:]])
    return job
