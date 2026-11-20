#!/usr/bin/env python3
"""Tiny wrapper: set resource limits on itself, then exec the user program.

usage: limit_exec.py CPU_S MEMORY_MB FSIZE_BYTES NOFILE NPROC -- program args...
(MEMORY_MB or NPROC of 0 leaves that limit alone.)

Used instead of preexec_fn, which is unsafe in threaded parents.
"""

import os
import resource
import sys


def setlim(res: int, soft: int, hard: int | None = None) -> None:
    try:
        resource.setrlimit(res, (soft, soft if hard is None else hard))
    except (ValueError, OSError):
        pass  # not supported on this platform (e.g. RLIMIT_AS on macOS)


def main() -> None:
    cpu, mem_mb, fsize, nofile, nproc = (int(x) for x in sys.argv[1:6])
    if sys.argv[6] != "--":
        raise SystemExit("usage: limit_exec.py CPU MEM FSIZE NOFILE NPROC -- argv...")
    argv = sys.argv[7:]
    setlim(resource.RLIMIT_CPU, cpu, cpu + 1)
    setlim(resource.RLIMIT_FSIZE, fsize)
    setlim(resource.RLIMIT_NOFILE, nofile)
    setlim(resource.RLIMIT_CORE, 0)
    if hasattr(resource, "RLIMIT_NPROC") and nproc > 0:  # 0 = leave alone (compilers fork)
        setlim(resource.RLIMIT_NPROC, nproc)
    if mem_mb > 0:
        # Deep recursion is normal in contest code: let the stack grow up to the memory
        # limit where the system allows it (macOS caps the hard limit at 64 MB).
        try:
            hard = resource.getrlimit(resource.RLIMIT_STACK)[1]
            want = mem_mb * 1024 * 1024
            setlim(resource.RLIMIT_STACK, want if hard == resource.RLIM_INFINITY else min(want, hard), hard)
        except (ValueError, OSError):
            pass
    if sys.platform.startswith("linux") and mem_mb > 0:
        # Address-space cap with headroom for the interpreter's own mappings.
        setlim(resource.RLIMIT_AS, (mem_mb + 96) * 1024 * 1024)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
