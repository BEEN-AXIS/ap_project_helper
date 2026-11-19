"""Match-engine harness: FakeClock + FakeRunner, a seeded database and fake sockets."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest
from sqlmodel import Session

from app.core.clock import FakeClock
from app.core.db import db_sync
from app.core.security import hash_password
from app.engine.actor import MatchActor
from app.main import build_context
from app.models import Profile, User
from app.realtime.hub import Connection
from app.seed import seed

_seeded = False
_names = itertools.count()


def ensure_seeded() -> None:
    global _seeded
    if not _seeded:
        seed(demo_users=False)
        _seeded = True


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed_with: int | None = None

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    def types(self) -> list[str]:
        return [m["type"] for m in self.sent]

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == type_]

    def last(self, type_: str) -> dict[str, Any]:
        return self.of(type_)[-1]


def make_player(rating: int = 1200, name: str | None = None) -> Profile:
    name = name or f"p{next(_names)}x{rating}"

    def work(s: Session) -> Profile:
        u = User(username=name, username_lower=name.lower(), password_hash=hash_password("unused-pass"))
        s.add(u)
        s.flush()
        p = Profile(user_id=u.id, display_name=name, rating=rating, peak_rating=rating)
        s.add(p)
        s.flush()
        return p

    return db_sync(work)


def reload_profile(pid: int) -> Profile:
    return db_sync(lambda s: s.get(Profile, pid))


class Arena:
    """A started two-player match with both sockets connected."""

    def __init__(self, ctx, actor: MatchActor, clock: FakeClock, ws: dict[int, FakeWS]) -> None:  # type: ignore[no-untyped-def]
        self.ctx = ctx
        self.actor = actor
        self.clock = clock
        self.ws = ws
        self._cmd = itertools.count()

    def cmd(self) -> str:
        return f"cmd-{next(self._cmd)}"

    async def settle(self) -> None:
        await self.actor.settle()

    async def advance(self, seconds: float) -> None:
        step = 0.5
        left = seconds
        while left > 0:
            dt = min(step, left)
            self.clock.advance(dt)
            left -= dt
            await self.settle()

    async def submit(self, side: int, slot: int, verdict: str = "AC", cmd_id: str | None = None, extra: str = "") -> Any:
        code = f"# VERDICT: {verdict}\n# DELAY_MS: 0\nprint(1)\n{extra}"
        return await self.actor.send("submit", side, {"slot": slot, "code": code, "language": "python"}, cmd_id or self.cmd())

    async def submit_and_judge(self, side: int, slot: int, verdict: str = "AC") -> Any:
        r = await self.submit(side, slot, verdict)
        await self.settle()
        return r

    def slot_with_tier(self, side: int, tier: int) -> int:
        return list(self.actor.hands[side].tiers).index(tier)

    def hp(self, side: int) -> int:
        return getattr(self.actor.m, f"player{side}_hp")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def make_arena():  # type: ignore[no-untyped-def]
    ensure_seeded()
    made: list[Any] = []

    async def _make(r1: int = 1200, r2: int = 1200, mode: str = "ranked", map_id: str = "bit", seed: int = 7,
                    connect: bool = True, bot_personality: str | None = None) -> Arena:
        clock = FakeClock()
        ctx = build_context(clock)
        await ctx.problems.reload()
        await ctx.pool.start()
        p1 = make_player(r1)
        if mode in ("bot", "practice"):
            p2 = await ctx.matches.bot_profile(bot_personality if mode == "bot" else "dummy")
            actor = await ctx.matches.create_match(mode, map_id, p1, p2, opponent_kind="bot" if mode == "bot" else "dummy", seed=seed)
        else:
            p2 = make_player(r2)
            actor = await ctx.matches.create_match(mode, map_id, p1, p2, seed=seed)
        ws: dict[int, FakeWS] = {}
        arena = Arena(ctx, actor, clock, ws)
        made.append(ctx)
        if connect:
            for side in (1, 2):
                if not getattr(actor.m, f"player{side}_is_bot"):
                    ws[side] = FakeWS()
                    await actor.send("join", side, {"conn": Connection(ws[side], 0), "last_seq": 0})
            await arena.settle()
            await arena.advance(3.1)
            assert actor.m.status == "live", actor.m.status
        return arena

    yield _make
    for ctx in made:
        await ctx.matches.shutdown()
        await ctx.pool.stop()
