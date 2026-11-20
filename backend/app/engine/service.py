"""Match creation and the registry of live match actors.

One process owns all live matches in this prototype. Scaling out needs sticky
routing by match id or a Redis-backed hub (see README).
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.clock import Clock
from app.core.db import run_db
from app.core.errors import AppError
from app.domain import hand as handlib
from app.domain import powerups
from app.domain.gameconfig import GameConfig
from app.domain.tiers import get_tier
from app.engine.actor import MatchActor
from app.judge.pool import JudgePool
from app.models import Match, Profile
from app.realtime.hub import Hub
from app.services.problems import ProblemCache

log = logging.getLogger("algoarena.matches")


def default_skins() -> dict[str, str]:
    return {"card": "card.classic", "avatar": "bean.plain"}


class MatchService:
    def __init__(self, cfg: GameConfig, clock: Clock, hub: Hub, pool: JudgePool, problems: ProblemCache) -> None:
        self.cfg = cfg
        self.clock = clock
        self.hub = hub
        self.pool = pool
        self.problems = problems
        self.registry: dict[str, MatchActor] = {}
        self.active: dict[int, str] = {}  # profile id -> live match id
        self.linger_handles: dict[str, asyncio.TimerHandle] = {}

    # ------------------------------------------------------------------ lookup
    def get(self, match_id: str) -> MatchActor | None:
        return self.registry.get(match_id)

    def active_match_for(self, profile_id: int) -> str | None:
        return self.active.get(profile_id)

    def live_matches(self) -> list[MatchActor]:
        return [a for a in self.registry.values() if not a.finished]

    # ------------------------------------------------------------------ lifecycle
    @staticmethod
    def abort_stale_sync(s: Session) -> int:
        """On start-up, any match still starting or live is aborted with no rating change."""
        rows = s.exec(select(Match).where(Match.status.in_(["starting", "live"]))).all()  # type: ignore[attr-defined]
        for m in rows:
            m.status = "aborted"
            m.end_reason = "aborted"
            m.outcome = "aborted"
            m.result = {"outcome": "aborted", "end_reason": "aborted", "reason": "server_restarted", "sides": {}}
            s.add(m)
        return len(rows)

    async def shutdown(self) -> None:
        for a in list(self.registry.values()):
            await a.stop()
        self.registry.clear()

    def on_finished_soon(self, actor: MatchActor):  # type: ignore[no-untyped-def]
        def _cb() -> None:
            for n in (1, 2):
                pid = actor.side(n).profile_id
                if self.active.get(pid) == actor.id:
                    self.active.pop(pid, None)
            loop = asyncio.get_running_loop()
            self.linger_handles[actor.id] = loop.call_later(
                self.cfg.match.registry_linger_s, lambda: asyncio.ensure_future(self._remove(actor.id)))

        return _cb

    async def _remove(self, match_id: str) -> None:
        actor = self.registry.pop(match_id, None)
        self.linger_handles.pop(match_id, None)
        self.hub.drop_room(match_id)
        if actor is not None:
            await actor.stop()

    # ------------------------------------------------------------------ creation
    def _snapshot(self, m: Match, n: int, prof: Profile | None, rating: int, mode: str, is_bot: bool,
                  name: str, skins: dict[str, Any]) -> None:
        tier = get_tier(rating, self.cfg)
        max_hp = self.cfg.tier_row(tier).max_hp
        blocks, hints = powerups.initial_charges(mode, self.cfg)
        if is_bot:
            blocks, hints = (0, 0) if mode == "practice" else (self.cfg.powerups.block.charges, 0)
        p = f"player{n}_"
        setattr(m, p + "profile_id", prof.id if prof else 0)
        setattr(m, p + "name", name)
        setattr(m, p + "rating", rating)
        setattr(m, p + "tier", tier)
        setattr(m, p + "max_hp", max_hp)
        setattr(m, p + "hp", max_hp)
        setattr(m, p + "skins", skins)
        setattr(m, p + "is_bot", is_bot)
        setattr(m, p + "blocks_left", blocks)
        setattr(m, p + "hints_left", hints)
        setattr(m, p + "rerolls_left", self.cfg.hand.reroll_max)
        setattr(m, p + "stats", {"lowest_hp": max_hp})

    def _skins_of(self, prof: Profile) -> dict[str, Any]:
        return {"card": prof.equipped_card, "avatar": prof.equipped_avatar, "arena": prof.equipped_arena,
                "weapon": prof.equipped_weapon, "color": prof.avatar_color}

    def _bot_weapon(self, personality: str | None) -> str:
        pers = self.cfg.bots.personalities.get(personality or "") or self.cfg.bots.personalities[self.cfg.bots.default_personality]
        return pers.weapon

    async def create_match(self, mode: str, map_id: str, p1: Profile, p2: Profile | None, *,
                           opponent_kind: str | None = None, seed: int | None = None) -> MatchActor:
        """Create the shared match row with both snapshots, deal both hands, start the actor."""
        if not self.problems.by_slug:
            raise AppError("server_error", "No problems are loaded; run the seed first")
        cfg = self.cfg
        map_cfg = cfg.map_cfg(map_id)
        seed = seed if seed is not None else secrets.randbits(31)
        rng = random.Random(seed)
        decks, warnings = handlib.build_decks(self.problems.pool, seed, map_cfg, cfg)
        for w in warnings:
            log.warning(w)
        m = Match(id=str(uuid.uuid4()), mode=mode, map=map_id, seed=seed, decks={str(k): v for k, v in decks.items()},
                  player1_profile_id=p1.id or 0, player2_profile_id=0)
        self._snapshot(m, 1, p1, p1.rating, mode, False, p1.display_name, self._skins_of(p1))
        if p2 is not None and not p2.is_bot:
            self._snapshot(m, 2, p2, p2.rating, mode, False, p2.display_name, self._skins_of(p2))
        else:
            assert p2 is not None, "a bot or dummy profile is required"
            if opponent_kind == "dummy":
                rating = p1.rating
                name = "Training Dummy"
            else:
                spread = cfg.bots.rating_spread
                rating = max(0, p1.rating + rng.randint(-spread, spread))
                name = p2.display_name
            skins = {"card": "card.classic", "avatar": "bean.plain", "arena": None, "color": p2.avatar_color,
                     "personality": p2.personality, "weapon": self._bot_weapon(p2.personality)}
            self._snapshot(m, 2, p2, rating, mode, True, name, skins)
        for n in (1, 2):
            tier = getattr(m, f"player{n}_tier")
            setattr(m, f"player{n}_hand", handlib.deal_hand(decks, tier, cfg).to_json())
        self._apply_stage(m, map_cfg.default_arena)

        def tx(s: Session) -> Match:
            s.add(m)
            return m

        await run_db(tx)
        actor = MatchActor(self, m)
        self.registry[m.id] = actor
        for n in (1, 2):
            if not getattr(m, f"player{n}_is_bot"):
                self.active[getattr(m, f"player{n}_profile_id")] = m.id
        actor.start()
        return actor

    async def create_bot_vs_bot(self, map_id: str, a: Profile, b: Profile, seed: int | None = None) -> MatchActor:
        """Two simulated bots (load testing and demos). Mode 'bot'; no human ratings change."""
        cfg = self.cfg
        seed = seed if seed is not None else secrets.randbits(31)
        decks, _ = handlib.build_decks(self.problems.pool, seed, cfg.map_cfg(map_id), cfg)
        m = Match(id=str(uuid.uuid4()), mode="bot", map=map_id, seed=seed, decks={str(k): v for k, v in decks.items()},
                  player1_profile_id=a.id or 0, player2_profile_id=b.id or 0)
        for n, p in ((1, a), (2, b)):
            skins = {"card": "card.classic", "avatar": "bean.plain", "arena": None, "color": p.avatar_color,
                     "personality": p.personality, "weapon": self._bot_weapon(p.personality)}
            self._snapshot(m, n, p, p.rating, "bot", True, p.display_name, skins)
            setattr(m, f"player{n}_hand", handlib.deal_hand(decks, getattr(m, f"player{n}_tier"), cfg).to_json())
        self._apply_stage(m, cfg.map_cfg(map_id).default_arena)
        await run_db(lambda s: s.add(m))
        actor = MatchActor(self, m)
        self.registry[m.id] = actor
        actor.start()
        return actor

    def _apply_stage(self, m: Match, default_theme: str) -> None:
        """Stage rule: both on the map default -> show it; otherwise the higher-rated
        player's theme (player 1 wins a tie)."""
        t1 = (m.player1_skins or {}).get("arena") or default_theme
        t2 = (m.player2_skins or {}).get("arena") or default_theme
        if t1 == default_theme and t2 == default_theme:
            m.stage_theme, m.stage_owner_side = default_theme, None
            return
        owner = 1 if m.player1_rating >= m.player2_rating else 2
        theme = t1 if owner == 1 else t2
        m.stage_theme = theme
        m.stage_owner_side = owner if theme != default_theme else None

    async def bot_profile(self, personality: str | None) -> Profile:
        want = personality or self.cfg.bots.default_personality

        def q(s: Session) -> Profile | None:
            return s.exec(select(Profile).where(Profile.is_bot == True, Profile.personality == want)).first()  # noqa: E712

        p = await run_db(q)
        if p is None:
            raise AppError("server_error", "Bot profiles are missing; run the seed first")
        return p
