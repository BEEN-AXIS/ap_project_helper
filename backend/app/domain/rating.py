"""The rating formula (a custom point system the design chat calls ELO).

Only snapshot values are used: tiers from match start, final HP, each player's
own max HP, elapsed seconds on the match clock and the winner's hits landed.
Shares are compared as exact fractions, never floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .gameconfig import GameConfig

Step = tuple[str, int, int]  # (label key, winner change, loser change)


@dataclass(frozen=True)
class RatingResult:
    steps: list[Step]
    winner: int
    loser: int


def speed_bracket(elapsed_s: int, cfg: GameConfig) -> str:
    for b in cfg.rating.speed_brackets:
        if elapsed_s <= b.max_s:
            return b.name
    return cfg.rating.slow_bracket_name


def rating_delta(
    w_tier: int,
    l_tier: int,
    w_hp: int,
    w_max: int,
    l_hp: int,
    l_max: int,
    elapsed_s: int,
    winner_hits: int,
    cfg: GameConfig,
) -> RatingResult:
    r = cfg.rating
    steps: list[Step] = [("win", r.win, -r.win)]

    d = l_tier - w_tier
    if d:
        steps.append(("rank_gap", r.rank_gap * d, -r.rank_gap * d))

    w_share = Fraction(w_hp, w_max)
    l_share = Fraction(l_hp, l_max)
    if w_share - l_share >= Fraction(r.flawless_points, 100):
        steps.append(("flawless", r.flawless_bonus, -r.flawless_bonus))
    elif w_share <= Fraction(r.narrow_win_share_pct, 100) and w_tier >= l_tier:
        steps.append(("narrow_win", -r.narrow_win_penalty, r.narrow_win_penalty))

    for b in r.speed_brackets:
        if elapsed_s <= b.max_s:
            steps.append((b.name, b.bonus, 0))
            break

    winner = sum(s[1] for s in steps)
    loser = sum(s[2] for s in steps)
    if winner_hits == 0:  # Hollow Victory, applied last; overrides the speed bonus
        steps.append(("hollow_victory", -winner, 0))
        winner = 0
    return RatingResult(steps=steps, winner=winner, loser=loser)


def scale_delta(delta: int, pct: int) -> int:
    """Multiply, then divide, rounding toward zero. Integers only."""
    q = abs(delta) * pct // 100
    return q if delta >= 0 else -q


def rematch_pct(previous_meetings_in_window: int, cfg: GameConfig) -> int:
    """100% for the first ranked match, 50% for the second, 25% from the third."""
    table = cfg.rating.rematch_multiplier_pct
    idx = min(previous_meetings_in_window, len(table) - 1)
    return table[idx]


def mode_pct(mode: str, is_human: bool, cfg: GameConfig) -> int:
    if mode == "ranked":
        return 100
    if mode == "bot":
        return cfg.rating.bot_multiplier_pct if is_human else 0
    if mode == "friendly":
        return cfg.rating.friendly_multiplier_pct
    return 0  # practice and anything unknown changes nothing


def apply_daily_cap(delta: int, gained_today: int, cap: int) -> int:
    """Cap gains only; losses are never capped."""
    if delta <= 0:
        return delta
    room = max(0, cap - gained_today)
    return min(delta, room)


def apply_rating(rating: int, delta: int, cfg: GameConfig) -> int:
    return max(cfg.rating.floor, rating + delta)
