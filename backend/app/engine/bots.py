"""Bots and the practice dummy. Labelled "BOT (simulated)" in the UI: no code runs.

A bot is a participant whose behaviour runs inside the match actor. It picks a
card by personality weights, "thinks" for a log-normal time whose median grows
with the problem tier, then sends a Submit command with a simulated verdict.
The chance of a correct result is clamp(0.5 + 0.12 * (bot_tier - problem_tier)
+ skill_offset, 0.05, 0.95). bot_time_scale shrinks every delay for demos.
The practice dummy is passive: it never attacks.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from app.core.errors import RuleError
from app.engine.actor import Command
from app.judge.runner import JobResult, TestVerdict

if TYPE_CHECKING:
    from app.engine.actor import MatchActor
    from app.models import Submission

BOT_CODE = "# BOT (simulated): no code was executed for this submission\n"


def success_chance(bot_tier: int, problem_tier: int, skill_offset: float) -> float:
    return max(0.05, min(0.95, 0.5 + 0.12 * (bot_tier - problem_tier) + skill_offset))


class BotBrain:
    def __init__(self, actor: MatchActor, side: int, personality: str) -> None:
        self.a = actor
        self.n = side
        self.cfg = actor.cfg
        self.p = self.cfg.bots.personalities[personality]
        self.rng = actor.rng.__class__(f"bot:{actor.m.seed}:{side}")
        self.target_slot: int | None = None

    @property
    def scale(self) -> float:
        return max(0.001, self.cfg.bot_time_scale) * self.p.time_scale

    def _think_seconds(self, problem_tier: int) -> float:
        median = self.cfg.bots.think_median_s[problem_tier - 1]
        return median * math.exp(self.rng.gauss(0, self.cfg.bots.think_sigma)) * self.scale

    def _pick_slot(self) -> int | None:
        hand = self.a.hands[self.n]
        weights = []
        for i, slug in enumerate(hand.slots):
            w = self.p.slot_weights[i] if slug is not None else 0
            if self.p.prefer_on_level and hand.tiers[i] == self.a.side(self.n).tier:
                w *= 3
            weights.append(w)
        if sum(weights) <= 0:
            options = [i for i, s in enumerate(hand.slots) if s is not None]
            return self.rng.choice(options) if options else None
        return self.rng.choices(range(len(weights)), weights=weights)[0]

    def _schedule(self, delay_s: float, action: str) -> None:
        self.a._schedule(f"bot:{self.n}", delay_s, "bot", side=self.n, action=action)

    # -- hooks called by the actor ------------------------------------------------
    def on_live(self) -> None:
        self._plan()

    def _plan(self, extra_wait: float = 0.0) -> None:
        slot = self._pick_slot()
        if slot is None:
            self._schedule(2 * self.scale + 0.05, "plan")
            return
        self.target_slot = slot
        tier = self.a.hands[self.n].tiers[slot]
        self._schedule(extra_wait + self._think_seconds(tier), "submit")

    def on_tick(self, data: dict[str, Any]) -> None:
        action = data.get("action")
        if action == "plan":
            self._plan()
            return
        if action != "submit":
            return
        slot = self.target_slot
        if slot is None or self.a.hands[self.n].slots[slot] is None:
            self._plan()
            return
        try:
            self.a._cmd_submit(Command("submit", self.n, {"slot": slot, "code": BOT_CODE, "language": "python",
                                                          "simulated": True}, None))
        except RuleError as e:
            retry = float(e.details.get("retry_after", 1.0)) if e.details else 1.0
            self._schedule(retry + 0.05, "submit")

    def on_submitted(self, sub: Submission, total: int) -> None:
        p = self.a.svc.problems.by_id[sub.problem_id]
        bot_tier = self.a.side(self.n).tier
        correct = self.rng.random() < success_chance(bot_tier, p.tier, self.p.skill_offset)
        lo, hi = self.cfg.bots.judge_delay_s
        delay = self.rng.uniform(lo, hi) * max(0.001, self.cfg.bot_time_scale)
        if correct:
            res = JobResult(compile_error=None, verdicts=[TestVerdict(i, "AC", 20, 9000) for i in range(total)])
        else:
            fail = self.rng.randrange(total)
            code = self.rng.choice(["WA", "WA", "WA", "TLE", "RE"])
            res = JobResult(compile_error=None, verdicts=[*(TestVerdict(i, "AC", 20, 9000) for i in range(fail)),
                                                          TestVerdict(fail, code, 20, 9000)])
        self.a._schedule(f"botv:{self.n}", delay, "bot_verdict", side=self.n, submission_id=sub.id, result=res, total=total)

    def after_verdict(self, mine: bool, verdict: str) -> None:
        me = self.a.side(self.n)
        if (not mine and me.blocks_left > 0 and me.hp * 100 < self.p.block_below_pct * me.max_hp
                and not me.shield_until_ms):
            try:
                self.a._cmd_block(Command("block", self.n, {}, None))
            except RuleError:
                pass
        if mine:
            if verdict == "AC":
                self._plan(extra_wait=1.0 * self.scale)
            else:
                lo, hi = self.cfg.bots.miss_wait_s
                wait = self.rng.uniform(lo, hi) * self.scale
                slot = self.target_slot
                tier = self.a.hands[self.n].tiers[slot] if slot is not None else 1
                self._schedule(wait + self._think_seconds(tier) * 0.5, "submit")


def make_brain(actor: MatchActor, side: int) -> BotBrain | None:
    sd = actor.side(side)
    if not sd.is_bot or actor.m.mode == "practice":
        return None
    personality = (sd.skins or {}).get("personality") or actor.cfg.bots.default_personality
    if personality not in actor.cfg.bots.personalities:
        personality = actor.cfg.bots.default_personality
    return BotBrain(actor, side, personality)
