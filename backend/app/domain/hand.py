"""Dealing hands of four cards.

Each player holds four cards of four consecutive problem tiers. For each tier
the dealer shuffles that tier's problems with a generator seeded from
(match seed, tier) into one deck that both players draw from independently,
so both players see the same problems for a tier in the same order.

Pure: the only randomness is a seeded random.Random built from the inputs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .gameconfig import GameConfig, MapCfg


@dataclass(frozen=True)
class PoolProblem:
    slug: str
    tier: int
    biome: str


@dataclass(frozen=True)
class HandState:
    tiers: tuple[int, ...]  # slot -> problem tier
    slots: tuple[str | None, ...]  # slot -> problem slug, None while awaiting a re-deal
    pointers: dict[int, int] = field(default_factory=dict)  # tier -> next deck index
    solved: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "tiers": list(self.tiers),
            "slots": list(self.slots),
            "pointers": {str(k): v for k, v in self.pointers.items()},
            "solved": list(self.solved),
        }

    @staticmethod
    def from_json(d: dict[str, object]) -> HandState:
        pointers = d.get("pointers") or {}
        assert isinstance(pointers, dict)
        return HandState(
            tiers=tuple(int(x) for x in d["tiers"]),  # type: ignore[union-attr]
            slots=tuple(d["slots"]),  # type: ignore[arg-type]
            pointers={int(k): int(v) for k, v in pointers.items()},
            solved=tuple(d.get("solved") or ()),  # type: ignore[arg-type]
        )


def hand_window(player_tier: int, cfg: GameConfig) -> list[int]:
    """lo = clamp(player_tier + window_offset, lo_min, lo_max); tiers lo..lo+3."""
    h = cfg.hand
    lo = max(h.window_lo_min, min(h.window_lo_max, player_tier + h.window_offset))
    return [lo + i for i in range(h.size)]


def difficulty_level(player_tier: int, problem_tier: int, cfg: GameConfig) -> int:
    """A card's place in the player's hand window: 0 easy, 1 normal, 2 medium, 3 tough.
    Cosmetic only (it picks the attack animation); damage comes from the tier difference."""
    lo = hand_window(player_tier, cfg)[0]
    return max(0, min(cfg.hand.size - 1, problem_tier - lo))


def deck_rng(seed: int, tier: int) -> random.Random:
    # Python's Random takes one seed; a string "seed:tier" is hashed
    # deterministically (version-2 seeding), so decks are stable across runs.
    return random.Random(f"{seed}:{tier}")


def build_decks(
    pool: list[PoolProblem], seed: int, map_cfg: MapCfg, cfg: GameConfig
) -> tuple[dict[int, list[str]], list[str]]:
    """Return one deck per tier plus warnings for thin tiers.

    A deck is the map's own problems for that tier (shuffled), followed by
    every other biome's problems for that tier (shuffled) as the fallback.
    """
    decks: dict[int, list[str]] = {}
    warnings: list[str] = []
    for row in cfg.tiers:
        tier = row.tier
        primary = sorted(p.slug for p in pool if p.tier == tier and p.biome in map_cfg.biomes)
        rest = sorted(p.slug for p in pool if p.tier == tier and p.biome not in map_cfg.biomes)
        rng = deck_rng(seed, tier)
        rng.shuffle(primary)
        rng.shuffle(rest)
        if len(primary) < cfg.hand.min_deck_per_tier:
            warnings.append(
                f"map {map_cfg.id} has {len(primary)} tier-{tier} problem(s); "
                "falling back to all biomes"
            )
        decks[tier] = primary + rest
    return decks, warnings


def _draw(hand: HandState, decks: dict[int, list[str]], tier: int) -> tuple[str | None, int]:
    """Next problem for a tier: skip problems already solved or held this match.

    Returns (slug, new_pointer). Once every problem is used it allows repeats,
    always advancing through the same deck order.
    """
    deck = decks.get(tier) or []
    if not deck:
        return None, hand.pointers.get(tier, 0)
    start = hand.pointers.get(tier, 0)
    held = {s for s in hand.slots if s is not None}
    for step in range(len(deck)):
        idx = start + step
        slug = deck[idx % len(deck)]
        if slug not in hand.solved and slug not in held:
            return slug, idx + 1
    # Every problem of this tier is solved or held: allow a repeat.
    for step in range(len(deck)):
        idx = start + step
        slug = deck[idx % len(deck)]
        if slug not in held:
            return slug, idx + 1
    return deck[start % len(deck)], start + 1


def deal_hand(decks: dict[int, list[str]], player_tier: int, cfg: GameConfig) -> HandState:
    tiers = tuple(hand_window(player_tier, cfg))
    hand = HandState(tiers=tiers, slots=tuple(None for _ in tiers), pointers={})
    for slot in range(len(tiers)):
        hand = fill_slot(hand, decks, slot)
    return hand


def fill_slot(hand: HandState, decks: dict[int, list[str]], slot: int) -> HandState:
    tier = hand.tiers[slot]
    slug, ptr = _draw(hand, decks, tier)
    slots = list(hand.slots)
    slots[slot] = slug
    pointers = dict(hand.pointers)
    pointers[tier] = ptr
    return replace(hand, slots=tuple(slots), pointers=pointers)


def consume_slot(hand: HandState, slot: int) -> HandState:
    """A correct attempt spends the card; the slot waits for a re-deal."""
    slug = hand.slots[slot]
    slots = list(hand.slots)
    slots[slot] = None
    solved = hand.solved + ((slug,) if slug else ())
    return replace(hand, slots=tuple(slots), solved=solved)


def reroll_slot(hand: HandState, decks: dict[int, list[str]], slot: int) -> HandState:
    """Swap one card for the next problem of the same tier."""
    current = hand.slots[slot]
    slots = list(hand.slots)
    slots[slot] = None
    cleared = replace(hand, slots=tuple(slots))
    refilled = fill_slot(cleared, decks, slot)
    if refilled.slots[slot] is None and current is not None:
        return hand
    return refilled


def slot_of(hand: HandState, slug: str) -> int | None:
    for i, s in enumerate(hand.slots):
        if s == slug:
            return i
    return None


def map_allowed(map_cfg: MapCfg, player_tier: int) -> bool:
    return player_tier >= map_cfg.min_tier
