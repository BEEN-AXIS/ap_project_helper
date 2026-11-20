"""Pick a free TCP port on 127.0.0.1, starting at the preferred one.

Usage: ports.py PREFERRED LABEL  ->  prints the chosen port on stdout.
When the preferred port is taken it says which process holds it (via lsof)
on stderr, so a server left over from an earlier run is easy to find.
"""
from __future__ import annotations

import socket
import subprocess
import sys


def busy(port: int) -> bool:
    # Something accepting connections (even a suspended process: the kernel accepts for it)...
    with socket.socket() as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return True
    # ...or a socket we cannot bind next to.
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def holder(port: int) -> str:
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    pids = [line[1:] for line in out.splitlines() if line.startswith("p")]
    if not pids:
        return ""
    try:
        cmd = subprocess.run(["ps", "-o", "stat=,command=", "-p", pids[0]], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        cmd = ""
    stat, _, command = cmd.partition(" ")
    stopped = " (it is suspended: probably a Ctrl-Z in some terminal)" if stat.startswith("T") else ""
    return f"PID {pids[0]}{stopped}: {command.strip()[:160]}"


def main() -> int:
    preferred = int(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else "server"
    if not busy(preferred):
        print(preferred)
        return 0
    who = holder(preferred)
    for port in range(preferred + 1, preferred + 20):
        if not busy(port):
            print(f"  ! Port {preferred} is already in use, so the {label} will use {port}.", file=sys.stderr)
            if who:
                print(f"    {who}", file=sys.stderr)
                print(f"    If that is an old AlgoArena run, stop it with: kill {who.split()[1].rstrip(':')}", file=sys.stderr)
            print(port)
            return 0
    print(f"  ! No free port between {preferred} and {preferred + 19} for the {label}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
