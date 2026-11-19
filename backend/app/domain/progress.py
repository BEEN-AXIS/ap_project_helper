"""Arena Points, daily quests and achievements, computed from a match summary.

Pure functions over plain data. Practice matches never reach these functions
with a non-zero result: callers skip them, and compute_ap returns nothing for
them as a second guard.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .gameconfig import GameConfig, QuestCfg


@dataclass(frozen=True)
class SideSummary:
    mode: str  # ranked | bot | practice | friendly
    map: str
    label: str | None  # victory | defeat | hollow_victory | self_destruct | draw | None (aborted)
    end_reason: str
    hits_landed: int = 0
    hits_stretching: int = 0  # hits with tier_diff <= -1
    heroic_hits: int = 0  # hits with tier_diff == -4
    crits: int = 0
    blocks_absorbed: int = 0  # incoming hits your Block absorbed
    backfires: int = 0
    accepted: int = 0
    submissions: int = 0
    accepted_run_after: int = 0  # trailing accepted submissions with no failure after them
    failed_any: bool = False
    flawless: bool = False
    blitz: bool = False
    elapsed_s: int = 0
    lowest_hp: int = 0
    max_hp: int = 1
    one_shot: bool = False  # KO'd the opponent from full HP with a single hit
    max_streak: int = 0

    @property
    def won(self) -> bool:
        return self.label in ("victory", "hollow_victory")

    @property
    def counts(self) -> bool:
        return self.mode != "practice" and self.label is not None


# Arena Points ---------------------------------------------------------------


def compute_ap(
    s: SideSummary, first_win_today: bool, casual_gained_today: int, cfg: GameConfig
) -> tuple[int, list[tuple[str, int]]]:
    e = cfg.economy
    if not s.counts:
        return 0, []
    lines: list[tuple[str, int]] = [("match", e.match)]
    if s.won:
        lines.append(("win", e.win))
    if s.label == "draw":
        lines.append(("draw", e.draw))
    if s.hits_landed:
        lines.append(("hits", min(e.per_match_hit_cap, e.per_hit * s.hits_landed)))
    if s.won and s.flawless:
        lines.append(("flawless", e.flawless))
    if s.won and s.blitz:
        lines.append(("blitz", e.blitz))
    if s.won and first_win_today:
        lines.append(("first_win_of_day", e.first_win_of_day))
    if s.max_streak >= 2:
        lines.append(("streak", min(e.streak_cap, e.streak_per_level * (s.max_streak - 1))))

    if s.mode in ("bot", "friendly"):
        lines = [(k, v * e.casual_modes_pct // 100) for k, v in lines]
        room = max(0, e.casual_modes_daily_cap - casual_gained_today)
        capped: list[tuple[str, int]] = []
        for k, v in lines:
            take = min(v, room)
            room -= take
            capped.append((k, take))
        if sum(v for _, v in capped) < sum(v for _, v in lines):
            capped.append(("daily_cap", 0))
        lines = capped
    lines = [(k, v) for k, v in lines if v > 0 or k == "daily_cap"]
    return sum(v for _, v in lines), lines


# Daily quests ---------------------------------------------------------------


def daily_quests(utc_date: str, cfg: GameConfig) -> list[QuestCfg]:
    """Three quests per day, a seeded random choice from the date (YYYY-MM-DD)."""
    rng = random.Random(f"quests:{utc_date}")
    pool = list(cfg.quests)
    rng.shuffle(pool)
    return sorted(pool[: cfg.quests_per_day], key=lambda q: q.id)


def quest_increment(q: QuestCfg, s: SideSummary) -> int:
    if not s.counts:
        return 0
    if q.kind == "hits":
        return s.hits_landed
    if q.kind == "hits_stretching":
        return s.hits_stretching
    if q.kind == "blocks_absorbed":
        return s.blocks_absorbed
    if q.kind == "win_on_map":
        return 1 if s.won and s.map == q.map else 0
    if q.kind == "finish_bot":
        return 1 if s.mode == "bot" else 0
    if q.kind == "win_no_backfire":
        return 1 if s.won and s.backfires == 0 else 0
    if q.kind == "matches_played":
        return 1
    return 0


# Achievements -----------------------------------------------------------------


@dataclass(frozen=True)
class Counters:
    career_blocks: int = 0
    ac_streak: int = 0
    ranked_win_streak: int = 0
    bit_wins: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, int]:
        return {
            "career_blocks": self.career_blocks,
            "ac_streak": self.ac_streak,
            "ranked_win_streak": self.ranked_win_streak,
            "bit_wins": self.bit_wins,
            **self.extra,
        }

    @staticmethod
    def from_json(d: dict[str, int] | None) -> Counters:
        d = dict(d or {})
        return Counters(
            career_blocks=d.pop("career_blocks", 0),
            ac_streak=d.pop("ac_streak", 0),
            ranked_win_streak=d.pop("ranked_win_streak", 0),
            bit_wins=d.pop("bit_wins", 0),
            extra=d,
        )


def update_counters(c: Counters, s: SideSummary) -> Counters:
    if not s.counts:
        return c
    ac = (c.ac_streak + s.accepted) if not s.failed_any else s.accepted_run_after
    rw = c.ranked_win_streak
    if s.mode == "ranked":
        rw = rw + 1 if s.won else 0
    return replace(
        c,
        career_blocks=c.career_blocks + s.blocks_absorbed,
        ac_streak=ac,
        ranked_win_streak=rw,
        bit_wins=c.bit_wins + (1 if s.won and s.map == "bit" else 0),
    )


def achievements_earned(
    s: SideSummary, after: Counters, already: set[str], cfg: GameConfig
) -> list[str]:
    """Achievement ids newly earned by this match (counters already updated)."""
    if not s.counts:
        return []
    out: list[str] = []
    for a in cfg.achievements:
        if a.id in already:
            continue
        hit = False
        if a.id == "flawless":
            hit = s.won and s.flawless
        elif a.id == "comeback":
            hit = s.won and s.lowest_hp * 100 <= (a.hp_pct or 10) * s.max_hp
        elif a.id == "one_shot":
            hit = s.won and s.one_shot
        elif a.id == "heroic":
            hit = s.heroic_hits > 0
        elif a.id == "wall":
            hit = after.career_blocks >= (a.target or 3)
        elif a.id == "crit_machine":
            hit = s.crits >= (a.target or 5)
        elif a.id == "bit_master":
            hit = after.bit_wins >= (a.target or 25)
        elif a.id == "perfectionist":
            hit = after.ac_streak >= (a.target or 10)
        elif a.id == "marathon":
            hit = s.elapsed_s > (a.min_s or 3600) and s.end_reason != "aborted"
        elif a.id == "hot_streak":
            hit = after.ranked_win_streak >= (a.target or 5)
        if hit:
            out.append(a.id)
    return out
