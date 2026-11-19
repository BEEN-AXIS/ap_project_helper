"""Load test: N simultaneous bot-vs-bot matches in one process.

    python scripts/load_test.py            # 50 matches (default)
    python scripts/load_test.py 100

Runs the real match actors, judge pool and database (SQLite in WAL mode by
default, or DATABASE_URL) with BOT_TIME_SCALE shrinking every bot delay, then
reports how many matches finished, how long it took and any errors. Bots use
simulated verdicts, so no code is executed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENV", "test")
os.environ.setdefault("BOT_TIME_SCALE", "0.003")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp(prefix='aa-load-')}/load.db")


async def main(n: int) -> int:
    import logging

    from sqlmodel import select

    from app.core.db import run_db
    from app.main import build_context
    from app.models import MatchEvent, Profile
    from app.seed import seed

    logging.basicConfig(level="ERROR")
    seed(demo_users=False)
    ctx = build_context()
    await ctx.problems.reload()
    await ctx.pool.start()
    bots = await run_db(lambda s: s.exec(select(Profile).where(Profile.is_bot == True, Profile.personality != "dummy")).all())  # noqa: E712
    maps = ["bit", "binary"]
    t0 = time.perf_counter()
    actors = []
    errors = 0
    for i in range(n):
        a, b = bots[i % len(bots)], bots[(i + 1) % len(bots)]
        actors.append(await ctx.matches.create_bot_vs_bot(maps[i % 2], a, b, seed=1000 + i))
    created = time.perf_counter() - t0
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not all(x.finished for x in actors):
        await asyncio.sleep(0.25)
    elapsed = time.perf_counter() - t0
    finished = [x for x in actors if x.finished]
    outcomes: dict[str, int] = {}
    for x in finished:
        key = f"{x.m.end_reason}/{x.m.outcome}"
        outcomes[key] = outcomes.get(key, 0) + 1
    ids = [x.id for x in actors]
    events = await run_db(lambda s: len(s.exec(select(MatchEvent).where(MatchEvent.match_id.in_(ids))).all()))  # type: ignore[attr-defined]
    for x in actors:
        if x.m.status in ("starting", "live"):
            errors += 1
    print(f"matches: {n}  created in {created:.2f}s  finished: {len(finished)}/{n}  wall time: {elapsed:.1f}s")
    print(f"events persisted: {events}  outcomes: {outcomes}")
    print(f"judge pool: {ctx.pool.metrics.snapshot(ctx.pool.queued)}")
    await ctx.matches.shutdown()
    await ctx.pool.stop()
    ok = errors == 0 and len(finished) == n
    print("LOAD TEST PASSED" if ok else f"LOAD TEST FAILED ({errors} unfinished)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)))
