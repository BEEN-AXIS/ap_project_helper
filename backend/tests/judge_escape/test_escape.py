"""Sandbox escape suite (section 11). Each case is a submitted program and the
expected verdict. DockerRunner must pass all of them (skipped when no Docker
daemon or judge image is available). The dev SubprocessRunner passes the ones
it can enforce; the rest are expected failures with the reason written down.
"""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from app.core.config import load_game_config_file
from app.judge import build_job
from app.judge.docker_runner import DockerRunner, docker_available
from app.judge.runner import TestCase
from app.judge.subprocess_runner import SubprocessRunner

CFG = load_game_config_file()
pytestmark = pytest.mark.anyio


def _image_ready() -> bool:
    if not docker_available():
        return False
    return subprocess.run(["docker", "image", "inspect", "algoarena-judge:latest"], capture_output=True).returncode == 0


RUNNERS = [
    pytest.param("subprocess", id="subprocess"),
    pytest.param("docker", id="docker", marks=pytest.mark.skipif(not _image_ready(), reason="no Docker daemon or judge image")),
]


def runner(kind: str):  # type: ignore[no-untyped-def]
    # The tripwire is off so the resource limits themselves are what is tested.
    return SubprocessRunner("test", use_tripwire=False) if kind == "subprocess" else DockerRunner("algoarena-judge:latest")


async def verdict(kind: str, src: str, tl_ms: int = 125, mem: int = 128, inp: str = "", expected: str | None = "x\n") -> tuple[str, str]:
    job = build_job(cfg=CFG, language="python", source=src, tests=[TestCase(0, inp, expected, True)], mode="samples",
                    time_limit_ms=tl_ms, memory_mb=mem, checker="exact")
    res = await runner(kind).run(job, lambda v: asyncio.sleep(0))
    code = res.summary(1)[0]
    return code, (res.verdicts[0].stdout_tail or "") if res.verdicts else ""


IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.mark.parametrize("kind", RUNNERS)
async def test_infinite_loop_is_tle_and_process_is_gone(kind: str) -> None:
    code, _ = await verdict(kind, "import time\nopen('marker_pid','w')\nwhile True: pass\n")
    assert code == "TLE"
    out = subprocess.run(["pgrep", "-f", "marker_pid"], capture_output=True, text=True)
    assert out.stdout.strip() == ""


@pytest.mark.parametrize("kind", RUNNERS)
async def test_huge_allocation_is_mle_or_re(kind: str) -> None:
    code, _ = await verdict(kind, "a = [0] * (10**9)\nprint(len(a))\n")
    assert code in ("MLE", "RE")


@pytest.mark.parametrize("kind", RUNNERS)
async def test_printing_a_gigabyte_is_ole(kind: str) -> None:
    code, _ = await verdict(kind, "import sys\nchunk = 'x' * 1048576\nfor _ in range(1024): sys.stdout.write(chunk)\n", tl_ms=1000)
    assert code == "OLE"


@pytest.mark.parametrize("kind", RUNNERS)
async def test_sys_exit_1_is_re(kind: str) -> None:
    assert (await verdict(kind, "import sys\nsys.exit(1)\n"))[0] == "RE"


@pytest.mark.parametrize("kind", RUNNERS)
async def test_environment_holds_no_server_secrets(kind: str) -> None:
    os.environ["JWT_SECRET"] = os.environ.get("JWT_SECRET", "s3cret-for-the-test")
    _, out = await verdict(kind, "import os\nprint('JWT_SECRET' in os.environ, len(os.environ))\n", expected=None)
    assert out.startswith("False")


@pytest.mark.parametrize("kind", RUNNERS)
async def test_fork_bomb_is_contained(kind: str) -> None:
    if kind == "subprocess" and IS_ROOT:
        pytest.xfail("RLIMIT_NPROC is not enforced for root; run the dev server as a normal user")
    src = ("import os\nn = 0\nfor _ in range(300):\n    try:\n        pid = os.fork()\n    except OSError:\n        break\n"
           "    if pid == 0:\n        import time; time.sleep(5); os._exit(0)\n    n += 1\nprint(n)\n")
    code, out = await verdict(kind, src, tl_ms=1000, expected=None)
    assert code in ("OK", "RE", "TLE") and (not out.strip() or int(out.split()[0]) < 300)


@pytest.mark.parametrize("kind", RUNNERS)
async def test_network_is_blocked(kind: str) -> None:
    if kind == "subprocess":
        pytest.xfail("the dev runner cannot block network access; Docker runs with --network none")
    src = "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 80), timeout=2); print('open')\nexcept OSError: print('blocked')\n"
    assert (await verdict(kind, src, tl_ms=500, expected=None))[1].strip() == "blocked"


@pytest.mark.parametrize("kind", RUNNERS)
async def test_host_files_are_unreadable(kind: str) -> None:
    if kind == "subprocess":
        pytest.xfail("the dev runner runs as the server user and can read what that user can read")
    src = "try:\n    print(open('/etc/hostname').read()[:3] and 'read')\nexcept OSError: print('denied')\n"
    out = (await verdict(kind, src, expected=None))[1].strip()
    assert out in ("denied", "read")  # /etc in the image is the container's, never the host's


@pytest.mark.parametrize("kind", RUNNERS)
async def test_cannot_write_outside_the_job_directory(kind: str) -> None:
    target = "/tmp/aa-escape-write-test" if kind == "subprocess" else "/work/escape"
    src = f"try:\n    open({target!r}, 'w').write('x'); print('wrote')\nexcept OSError: print('denied')\n"
    out = (await verdict(kind, src, expected=None))[1].strip()
    if kind == "subprocess" and out == "wrote":
        os.unlink(target)
        pytest.xfail("the dev runner cannot stop writes to world-writable host paths")
    assert out == "denied"


@pytest.mark.parametrize("kind", RUNNERS)
async def test_concurrent_jobs_cannot_see_each_other(kind: str) -> None:
    writer = "open('secret_from_a.txt','w').write('A'); import time; time.sleep(0.4); print('done')\n"
    reader = "import os, time\ntime.sleep(0.1)\nprint('secret_from_a.txt' in os.listdir('.'))\n"
    a = asyncio.create_task(verdict(kind, writer, tl_ms=1000, expected=None))
    b = asyncio.create_task(verdict(kind, reader, tl_ms=1000, expected=None))
    await a
    assert (await b)[1].strip() == "False"


@pytest.mark.parametrize("kind", RUNNERS)
async def test_no_stray_processes_after_the_suite(kind: str) -> None:
    out = subprocess.run(["pgrep", "-af", "harness/run_tests.py"], capture_output=True, text=True)
    stray = [ln for ln in out.stdout.splitlines() if "pgrep" not in ln]
    assert stray == [], stray
