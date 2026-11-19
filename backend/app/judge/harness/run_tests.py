#!/usr/bin/env python3
"""Judge harness. Runs inside the sandbox (Docker) or as the dev runner's child.

Reads one job spec as JSON on stdin, writes the source into the current
directory, compiles it, then runs each test through limit_exec.py with the
input on stdin. Prints one JSON object per line:

  {"type": "compile_error", "message": "line 3: invalid syntax"}
  {"type": "test", "index": 0, "status": "OK|TLE|MLE|RE|OLE", "time_ms", "memory_kb", "stdout", "stderr_tail"}
  {"type": "done"}

It never sees expected outputs: comparing is done by the caller, outside the
sandbox. Standalone on purpose: it imports nothing from the app.
"""

from __future__ import annotations

import json
import math
import os
import re
import resource
import signal
import subprocess
import sys
import time

try:  # psutil polls resident memory where RLIMIT_AS is not enforced (macOS)
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None

HERE = os.path.dirname(os.path.abspath(__file__))
LIMIT_EXEC = os.path.join(HERE, "limit_exec.py")
MAXRSS_IN_BYTES = sys.platform == "darwin"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def kill_group(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def tree_rss(pid: int) -> int:
    proc = psutil.Process(pid)
    total = proc.memory_info().rss
    for c in proc.children(recursive=True):
        try:
            total += c.memory_info().rss
        except psutil.Error:
            pass
    return total


_PATH_RE = re.compile(r'(/[^\s"\']+/)([^/\s"\']+)')


def scrub(text: str, workdir: str) -> str:
    text = text.replace(workdir + os.sep, "").replace(workdir, ".")
    return _PATH_RE.sub(lambda m: m.group(2), text)


def run_one(argv: list[str], test_input: str, lim: dict, workdir: str, env: dict) -> dict:
    in_path, out_path, err_path = (os.path.join(workdir, n) for n in (".in", ".out", ".err"))
    with open(in_path, "w", encoding="utf-8") as f:
        f.write(test_input)
    time_ms = int(lim["time_ms"])
    cpu_s = max(1, math.ceil(time_ms / 1000))
    wall_s = lim["wall_ms"] / 1000.0
    mem_bytes = int(lim["memory_mb"]) * 1024 * 1024
    out_cap = int(lim["output_kb"]) * 1024
    cmd = [
        sys.executable, LIMIT_EXEC, str(cpu_s), str(lim["memory_mb"]), str(lim["fsize_bytes"]),
        str(lim["nofile"]), str(lim["nproc"]), "--", *argv,
    ]
    ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.monotonic()
    killed = None
    peak = 0
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout, open(err_path, "wb") as ferr:
        p = subprocess.Popen(cmd, stdin=fin, stdout=fout, stderr=ferr, cwd=workdir, env=env,
                             start_new_session=True, close_fds=True)
        while p.poll() is None:
            elapsed = time.monotonic() - t0
            if elapsed > wall_s:
                killed = "TLE"
                kill_group(p)
                break
            if psutil is not None:
                try:
                    rss = tree_rss(p.pid)
                    peak = max(peak, rss)
                    if rss > mem_bytes:
                        killed = "MLE"
                        kill_group(p)
                        break
                except Exception:
                    pass
            time.sleep(0.003 if elapsed < 0.05 else 0.01)
        rc = p.wait()
        kill_group(p)  # reap anything the program left behind
    ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = int(((ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)) * 1000)
    maxrss_kb = ru1.ru_maxrss // 1024 if MAXRSS_IN_BYTES else ru1.ru_maxrss
    memory_kb = peak // 1024 if peak else maxrss_kb

    out_size = os.path.getsize(out_path)
    with open(out_path, "rb") as f:
        stdout = f.read(out_cap + 1).decode("utf-8", errors="replace")
    with open(err_path, "rb") as f:
        f.seek(max(0, os.path.getsize(err_path) - int(lim["stderr_tail_kb"]) * 1024))
        stderr_tail = scrub(f.read().decode("utf-8", errors="replace"), workdir)

    if killed:
        status = killed
    elif out_size > out_cap or "File too large" in stderr_tail:
        # CPython ignores SIGXFSZ, so hitting the file-size cap shows up as an
        # OSError and exit code 1 rather than a signal: it is still OLE.
        status = "OLE"
    elif rc < 0:
        sig = -rc
        if sig == getattr(signal, "SIGXCPU", -1) or (sig == signal.SIGKILL and cpu_ms >= time_ms):
            status = "TLE"
        elif sig == getattr(signal, "SIGXFSZ", -1):
            status = "OLE"
        else:
            status = "RE"
            stderr_tail = (stderr_tail + f"\nkilled by signal {sig}").strip()
    elif rc > 0:
        status = "MLE" if "MemoryError" in stderr_tail else "RE"
        if status == "RE" and not stderr_tail:
            stderr_tail = f"exit code {rc}"
    elif cpu_ms > time_ms:
        status = "TLE"
    else:
        status = "OK"
    if status == "OLE":
        stdout = stdout[:out_cap]
    return {"status": status, "time_ms": cpu_ms, "memory_kb": int(memory_kb), "stdout": stdout, "stderr_tail": stderr_tail}


def main() -> None:
    spec = json.loads(sys.stdin.read())
    workdir = os.getcwd()
    src_name = spec.get("file", "main.py")
    source = spec["source"]
    with open(os.path.join(workdir, src_name), "w", encoding="utf-8") as f:
        f.write(source)
    if spec.get("language", "python") == "python":
        try:
            compile(source, src_name, "exec", dont_inherit=True)
        except SyntaxError as e:
            emit({"type": "compile_error", "message": f"line {e.lineno}: {e.msg}"})
            emit({"type": "done"})
            return
        except ValueError as e:
            emit({"type": "compile_error", "message": str(e)})
            emit({"type": "done"})
            return
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "HOME": workdir,
    }
    argv = [a.replace("{src}", src_name) for a in spec["run"]]
    for t in spec["tests"]:
        res = run_one(argv, t["input"], spec["limits"], workdir, env)
        res.update(type="test", index=t["index"])
        emit(res)
        if spec.get("stop_on_first_fail") and res["status"] != "OK":
            break
    emit({"type": "done"})


if __name__ == "__main__":
    main()
