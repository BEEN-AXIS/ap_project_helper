"""Block and Hint rules. Pure: callers pass the current time in milliseconds."""

from __future__ import annotations

from .gameconfig import GameConfig


def shield_active(shield_until_ms: int | None, now_ms: int) -> bool:
    return shield_until_ms is not None and now_ms < shield_until_ms


def shield_until(now_ms: int, cfg: GameConfig) -> int:
    return now_ms + cfg.powerups.block.window_s * 1000


def initial_charges(mode: str, cfg: GameConfig) -> tuple[int, int]:
    """(blocks, hints). Practice: no Block and unlimited hints (-1)."""
    if mode == "practice":
        return 0, -1
    return cfg.powerups.block.charges, cfg.powerups.hint.charges


def next_hint_level(revealed: int, cfg: GameConfig) -> int | None:
    """Levels go 1, 2, 3 in order; None once every level is shown."""
    nxt = revealed + 1
    return nxt if nxt <= cfg.powerups.hint.levels else None


def spend(charges: int) -> int:
    """-1 means unlimited."""
    return charges if charges < 0 else charges - 1


def has_charge(charges: int) -> bool:
    return charges < 0 or charges > 0
