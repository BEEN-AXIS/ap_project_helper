"""python -m app.seed_check [slug ...] [--brute] [--lang python|cpp]

Runs every problem's reference solutions through the configured judge runner:
the Python one stored with the problem and seed/solutions_cpp/<slug>.cpp when
the judge can compile C++. Fails if any test disagrees or any solution uses
more than half of the time limit. With --brute it also runs seed/brute/<slug>.py on the hidden tests and
expects it to fail (TLE or MLE): slow, so it is opt-in.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import BACKEND_DIR, get_game_config, get_settings
from app.judge import build_job, language_tools_present, make_runner
from app.judge.runner import TestCase, no_progress
from app.seed import load_problem_files


def references(data: dict, langs: set[str] | None) -> list[tuple[str, str]]:
    out = [("python", data["reference_solution"])]
    cpp = BACKEND_DIR / "seed" / "solutions_cpp" / f"{data['slug']}.cpp"
    if cpp.exists():
        out.append(("cpp", cpp.read_text()))
    return [(lang, src) for lang, src in out if not langs or lang in langs]


async def check_problem(runner, data: dict, brute: bool, langs: set[str] | None = None) -> list[str]:  # type: ignore[no-untyped-def]
    cfg = get_game_config()
    errors: list[str] = []
    tests = [TestCase(i, t["input"], t["expected"], t["is_sample"]) for i, t in enumerate(data["tests"])]
    present = language_tools_present(cfg, runner.name)
    parts: list[str] = []
    for lang, source in references(data, langs):
        if not present.get(lang, False):
            parts.append(f"{lang}: skipped (no compiler)")
            continue
        job = build_job(cfg=cfg, language=lang, source=source, tests=tests, mode="full",
                        time_limit_ms=data["time_limit_ms"], memory_mb=data["memory_mb"], checker=data["checker"])
        job.stop_on_first_fail = False
        res = await runner.run(job, no_progress)
        verdict, failed, passed = res.summary(len(tests))
        half = job.limits.time_ms // 2
        slowest = max((v.time_ms for v in res.verdicts), default=0)
        if verdict != "AC":
            errors.append(f"{lang} reference got {verdict} on test {failed} ({res.compile_error or res.system_message})")
        if slowest > half:
            errors.append(f"{lang} reference took {slowest} ms, over half the limit ({half} ms)")
        parts.append(f"{lang} {verdict} {passed}/{len(tests)} slowest {slowest} ms / half limit {half} ms")
    line = f"{data['slug']:18s} " + " | ".join(parts)
    if brute:
        path = BACKEND_DIR / "seed" / "brute" / f"{data['slug']}.py"
        if path.exists():
            hidden = [t for t in tests if not t.is_sample]
            bjob = build_job(cfg=cfg, language="python", source=path.read_text(), tests=hidden, mode="full",
                             time_limit_ms=data["time_limit_ms"], memory_mb=data["memory_mb"], checker=data["checker"])
            bres = await runner.run(bjob, no_progress)
            bv, bf, _ = bres.summary(len(hidden))
            line += f" | brute force: {bv} on hidden test {bf}"
            if bv == "AC":
                errors.append("the brute force passed every hidden test")
    print(line, flush=True)
    return errors


async def main_async(slugs: set[str], brute: bool, langs: set[str] | None = None) -> int:
    runner = make_runner(get_settings())
    print(f"runner: {runner.name} (sandboxed={runner.sandboxed})")
    failures = 0
    for data in load_problem_files():
        if slugs and data["slug"] not in slugs:
            continue
        for e in await check_problem(runner, data, brute, langs):
            failures += 1
            print(f"  FAIL {data['slug']}: {e}")
    print("seed-check passed" if not failures else f"seed-check FAILED ({failures})")
    return 1 if failures else 0


def main() -> None:
    argv = sys.argv[1:]
    langs = None
    if "--lang" in argv:
        i = argv.index("--lang")
        langs = {argv[i + 1]}
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    sys.exit(asyncio.run(main_async(set(args), "--brute" in argv, langs)))


if __name__ == "__main__":
    main()
