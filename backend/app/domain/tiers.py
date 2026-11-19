"""Rank tiers. Pure functions: no I/O, no clock, no randomness."""

from __future__ import annotations

from .gameconfig import GameConfig, TierRow


def get_tier(rating: int, cfg: GameConfig) -> int:
    """Map a player's rating or a problem's rating to a tier (1..N).

    With the default table: 1 below 1200, 2 below 1400, 3 below 1600,
    4 below 1900, otherwise 5.
    """
    tier = 1
    for row in cfg.tiers:
        if rating >= row.min_rating:
            tier = row.tier
    return tier


def tier_row_for_rating(rating: int, cfg: GameConfig) -> TierRow:
    return cfg.tier_row(get_tier(rating, cfg))


def max_hp_for_rating(rating: int, cfg: GameConfig) -> int:
    return tier_row_for_rating(rating, cfg).max_hp


def clamp_rating(rating: int, cfg: GameConfig) -> int:
    return max(cfg.rating.floor, rating)
