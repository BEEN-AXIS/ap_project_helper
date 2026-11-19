"""Output checkers. Comparison always follows the problem's checker, never a raw string match."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile

CHECKERS = ("exact", "tokens", "float", "unordered_lines", "custom")


def _lines(text: str) -> list[str]:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def exact(expected: str, actual: str) -> bool:
    """Line by line after trimming trailing spaces and ignoring trailing blank lines."""
    return _lines(expected) == _lines(actual)


def tokens(expected: str, actual: str) -> bool:
    return expected.split() == actual.split()


def _num(tok: str) -> float | None:
    try:
        v = float(tok)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def float_tokens(expected: str, actual: str, eps: float = 1e-6) -> bool:
    e, a = expected.split(), actual.split()
    if len(e) != len(a):
        return False
    for x, y in zip(e, a, strict=True):
        fx, fy = _num(x), _num(y)
        if fx is None or fy is None:
            if x != y:
                return False
            continue
        if abs(fx - fy) > eps and abs(fx - fy) > eps * max(abs(fx), abs(fy)):
            return False
    return True


def unordered_lines(expected: str, actual: str) -> bool:
    return sorted(_lines(expected)) == sorted(_lines(actual))


def custom(script: str, test_input: str, expected: str, actual: str, timeout_s: float = 5.0) -> bool:
    """Run a problem's checker script: argv input expected actual; exit 0 means pass.

    Dev-grade: runs with the judge's subprocess limits applied by the caller's
    sandbox only when the Docker runner is in use. No seed problem needs it.
    """
    with tempfile.TemporaryDirectory(prefix="aa-chk-") as d:
        paths = []
        for name, content in (("checker.py", script), ("in.txt", test_input), ("exp.txt", expected), ("out.txt", actual)):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            paths.append(p)
        try:
            r = subprocess.run([sys.executable, *paths], cwd=d, env={"PATH": os.environ.get("PATH", "")},
                               capture_output=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False
        return r.returncode == 0


def check(name: str, expected: str, actual: str, test_input: str = "", script: str | None = None) -> bool:
    if name == "exact":
        return exact(expected, actual)
    if name == "tokens":
        return tokens(expected, actual)
    if name == "float":
        return float_tokens(expected, actual)
    if name == "unordered_lines":
        return unordered_lines(expected, actual)
    if name == "custom":
        if not script:
            raise ValueError("custom checker needs a script")
        return custom(script, test_input, expected, actual)
    raise ValueError(f"unknown checker {name!r}")
