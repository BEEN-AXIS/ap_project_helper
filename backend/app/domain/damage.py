"""Tier-difference damage and recoil. Integer maths only.

These functions deliberately take no skin, cosmetic or player id: skins never
change a number (a test asserts the signatures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .gameconfig import GameConfig

DamageClass = Literal["light", "heavy", "massive", "nuke"]


@dataclass(frozen=True)
class Preview:
    damage: int
    recoil: int
    tier_diff: int
    scenario: str
    crit: bool
    dmg_pct: int
    recoil_pct: int


def _clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def multiplier_pcts(tier_diff: int, cfg: GameConfig) -> tuple[int, int]:
    m = cfg.multiplier
    dmg_pct = _clamp(100 - m.step_pct * tier_diff, m.min_pct, m.max_pct)
    recoil_pct = _clamp(100 + m.step_pct * tier_diff, m.min_pct, m.max_pct)
    return dmg_pct, recoil_pct


def scenario_name(tier_diff: int, cfg: GameConfig) -> str:
    return cfg.scenarios[str(tier_diff)]


def is_crit(tier_diff: int, cfg: GameConfig) -> bool:
    return tier_diff <= cfg.crit_max_tier_diff


def compute_preview(
    player_tier: int,
    problem_tier: int,
    base_damage: int,
    base_recoil: int,
    cfg: GameConfig,
) -> Preview:
    """Damage on a correct submission and recoil on a wrong one.

    tier_diff = player_tier - problem_tier
    dmg_pct    = clamp(100 - 20 * tier_diff, 20, 180)
    recoil_pct = clamp(100 + 20 * tier_diff, 20, 180)
    damage     = base_damage * dmg_pct // 100
    recoil     = base_recoil * recoil_pct // 100
    """
    diff = player_tier - problem_tier
    dmg_pct, recoil_pct = multiplier_pcts(diff, cfg)
    return Preview(
        damage=base_damage * dmg_pct // 100,
        recoil=base_recoil * recoil_pct // 100,
        tier_diff=diff,
        scenario=scenario_name(diff, cfg),
        crit=is_crit(diff, cfg),
        dmg_pct=dmg_pct,
        recoil_pct=recoil_pct,
    )


def damage_class(amount: int, max_hp: int, cfg: GameConfig) -> DamageClass:
    """Light under 10% of max HP, Heavy under 25%, Massive under 50%, else Nuke.

    For attacks compare against the defender's max HP; for backfires against
    the attacker's own max HP.
    """
    c = cfg.damage_classes
    scaled = amount * 100
    if scaled < c.light_below_pct * max_hp:
        return "light"
    if scaled < c.heavy_below_pct * max_hp:
        return "heavy"
    if scaled < c.massive_below_pct * max_hp:
        return "massive"
    return "nuke"


def apply_hp_loss(hp: int, amount: int) -> int:
    """HP never goes below zero."""
    return max(0, hp - amount)
