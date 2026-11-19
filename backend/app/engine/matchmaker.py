"""Matchmaker: pairs queued players by rating window and runs the ready-check.

The window starts at 50 and widens by 25 every 5 s of waiting, up to 400.
Two players match when their gap is within the smaller of their windows. The
loop runs every 500 ms, sorts by rating and pairs nearest neighbours, longest
wait first. A labelled bot is offered after BOT_FALLBACK_SECONDS; it only
starts when the player asks for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.db import run_db
from app.core.errors import AppError
from app.domain.gameconfig import GameConfig
from app.domain.tiers import get_tier
from app.engine.service import MatchService
from app.models import Profile, utcnow
from app.realtime.hub import Hub

log = logging.getLogger("algoarena.queue")


@dataclass
class Entry:
    profile_id: int
    name: str
    rating: int
    tier: int
    map: str  # a map id or "any"
    joined_at: float
    ip: str = ""
    mode: str = "ranked"


@dataclass
class Proposal:
    id: str
    a: Entry
    b: Entry
    map: str
    expires_at: float
    accepted: set[int] = field(default_factory=set)


class Matchmaker:
    def __init__(self, cfg: GameConfig, hub: Hub, matches: MatchService, now=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self.cfg = cfg
        self.hub = hub
        self.matches = matches
        self.now = now
        self.queue: dict[int, Entry] = {}
        self.proposals: dict[str, Proposal] = {}
        self.cooldowns: dict[int, float] = {}
        self.recent: dict[frozenset[int], float] = {}
        self.leave_timers: dict[int, asyncio.TimerHandle] = {}
        self._task: asyncio.Task[None] | None = None
        self._last_tick_push = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="matchmaker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.matchmaking.tick_ms / 1000)
            try:
                await self.tick()
            except Exception as e:  # pragma: no cover
                log.exception("matchmaker tick failed", exc_info=e)

    # ------------------------------------------------------------------ queue API
    def window(self, e: Entry) -> int:
        mm = self.cfg.matchmaking
        steps = int((self.now() - e.joined_at) // mm.window_step_s)
        return min(mm.window_max, mm.window_start + steps * mm.window_step)

    def status(self, profile_id: int) -> dict[str, Any]:
        e = self.queue.get(profile_id)
        if e is None:
            for p in self.proposals.values():
                if profile_id in (p.a.profile_id, p.b.profile_id):
                    return {"state": "proposal", "proposal_id": p.id}
            return {"state": "idle"}
        wait = self.now() - e.joined_at
        fallback = self.cfg.matchmaking.bot_fallback_s
        return {"state": "queued", "wait_s": round(wait, 1), "window": self.window(e), "map": e.map,
                "bot_available": wait >= fallback, "bot_in_s": max(0, round(fallback - wait, 1))}

    async def join(self, prof: Profile, map_id: str, ip: str = "") -> dict[str, Any]:
        pid = prof.id or 0
        if prof.queue_ban_until and prof.queue_ban_until > utcnow():
            raise AppError("forbidden", "Queue ban for leaving matches early", {"until": prof.queue_ban_until.isoformat()})
        cd = self.cooldowns.get(pid, 0) - self.now()
        if cd > 0:
            raise AppError("cooldown", "You declined a match; wait a moment", {"retry_after": cd})
        if self.matches.active_match_for(pid):
            raise AppError("conflict", "You are already in a match", {"match_id": self.matches.active_match_for(pid)})
        tier = get_tier(prof.rating, self.cfg)
        if map_id != "any":
            try:
                mc = self.cfg.map_cfg(map_id)
            except KeyError:
                raise AppError("validation", "Unknown map") from None
            if tier < mc.min_tier:
                raise AppError("forbidden", f"The {map_id} map needs tier {mc.min_tier} or higher")
        prev = self.queue.get(pid)
        self.queue[pid] = Entry(pid, prof.display_name, prof.rating, tier, map_id,
                                prev.joined_at if prev else self.now(), ip)
        self._cancel_leave(pid)
        await self.hub.lobby_send(pid, "queue.joined", self.status(pid))
        return self.status(pid)

    async def leave(self, profile_id: int) -> None:
        self.queue.pop(profile_id, None)
        self._cancel_leave(profile_id)

    def lobby_closed(self, profile_id: int) -> None:
        """A closed lobby socket leaves the queue after a short grace period."""
        if profile_id not in self.queue:
            return
        self._cancel_leave(profile_id)
        loop = asyncio.get_running_loop()
        self.leave_timers[profile_id] = loop.call_later(
            self.cfg.matchmaking.lobby_leave_grace_s, lambda: self.queue.pop(profile_id, None))

    def lobby_opened(self, profile_id: int) -> None:
        self._cancel_leave(profile_id)

    def _cancel_leave(self, pid: int) -> None:
        h = self.leave_timers.pop(pid, None)
        if h:
            h.cancel()

    # ------------------------------------------------------------------ pairing
    def _compatible_map(self, a: Entry, b: Entry) -> str | None:
        if a.map != "any" and b.map != "any":
            return a.map if a.map == b.map else None
        fixed = a.map if a.map != "any" else b.map
        if fixed != "any":
            return fixed
        options = [m.id for m in self.cfg.maps if min(a.tier, b.tier) >= m.min_tier]
        return random.Random(f"{a.profile_id}:{b.profile_id}:{int(a.joined_at)}").choice(options)

    def find_pairs(self) -> list[tuple[Entry, Entry, str]]:
        mm = self.cfg.matchmaking
        entries = sorted(self.queue.values(), key=lambda e: e.joined_at)
        by_rating = sorted(entries, key=lambda e: e.rating)
        taken: set[int] = set()
        pairs: list[tuple[Entry, Entry, str]] = []
        now = self.now()
        for e in entries:
            if e.profile_id in taken:
                continue
            best: tuple[int, Entry, str] | None = None
            for o in by_rating:
                if o.profile_id == e.profile_id or o.profile_id in taken:
                    continue
                gap = abs(o.rating - e.rating)
                if gap > min(self.window(e), self.window(o)):
                    continue
                map_id = self._compatible_map(e, o)
                if map_id is None:
                    continue
                met = self.recent.get(frozenset((e.profile_id, o.profile_id)))
                if met and now - met < mm.recent_opponent_min * 60:
                    if max(now - e.joined_at, now - o.joined_at) <= mm.recent_override_wait_s:
                        continue
                if mm.same_ip_block and e.ip and e.ip == o.ip:
                    continue
                if best is None or gap < best[0]:
                    best = (gap, o, map_id)
            if best is not None:
                taken.update((e.profile_id, best[1].profile_id))
                pairs.append((e, best[1], best[2]))
        return pairs

    async def tick(self) -> None:
        now = self.now()
        for a, b, map_id in self.find_pairs():
            self.queue.pop(a.profile_id, None)
            self.queue.pop(b.profile_id, None)
            p = Proposal(secrets.token_urlsafe(8), a, b, map_id, now + self.cfg.matchmaking.ready_check_s)
            self.proposals[p.id] = p
            for me, other in ((a, b), (b, a)):
                await self.hub.lobby_send(me.profile_id, "match.found", {
                    "proposal_id": p.id, "expires_in": self.cfg.matchmaking.ready_check_s, "map": map_id,
                    "opponent": {"name": other.name, "rating": other.rating, "tier": other.tier}})
        for p in list(self.proposals.values()):
            if p.expires_at <= now:
                await self._expire(p)
        if now - self._last_tick_push >= 1.0:
            self._last_tick_push = now
            for pid in list(self.queue):
                await self.hub.lobby_send(pid, "queue.tick", self.status(pid))

    async def _expire(self, p: Proposal) -> None:
        self.proposals.pop(p.id, None)
        for e in (p.a, p.b):
            if e.profile_id in p.accepted:
                self.queue[e.profile_id] = e  # wait time intact
                await self.hub.lobby_send(e.profile_id, "queue.joined", self.status(e.profile_id))
            else:
                await self._cooldown(e.profile_id)

    async def _cooldown(self, pid: int) -> None:
        until = self.now() + self.cfg.matchmaking.decline_cooldown_s
        self.cooldowns[pid] = until
        await self.hub.lobby_send(pid, "queue.cooldown", {"seconds": self.cfg.matchmaking.decline_cooldown_s})

    async def respond(self, profile_id: int, proposal_id: str, accept: bool) -> dict[str, Any]:
        p = self.proposals.get(proposal_id)
        if p is None or profile_id not in (p.a.profile_id, p.b.profile_id):
            raise AppError("not_found", "That match offer has expired")
        if not accept:
            self.proposals.pop(p.id, None)
            await self._cooldown(profile_id)
            other = p.b if p.a.profile_id == profile_id else p.a
            self.queue[other.profile_id] = other
            await self.hub.lobby_send(other.profile_id, "queue.joined", {**self.status(other.profile_id), "requeued": True})
            return {"state": "declined"}
        p.accepted.add(profile_id)
        if len(p.accepted) < 2:
            return {"state": "waiting"}
        self.proposals.pop(p.id, None)

        def load(s):  # type: ignore[no-untyped-def]
            return s.get(Profile, p.a.profile_id), s.get(Profile, p.b.profile_id)

        pa, pb = await run_db(load)
        actor = await self.matches.create_match("ranked", p.map, pa, pb)
        self.recent[frozenset((p.a.profile_id, p.b.profile_id))] = self.now()
        for e in (p.a, p.b):
            await self.hub.lobby_send(e.profile_id, "match.ready", {"match_id": actor.id})
        return {"state": "ready", "match_id": actor.id}
