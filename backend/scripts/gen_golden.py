"""Generate the frozen parts of shared/golden/*.json from the reference functions.

The hand-written anchors (the brief's 5x5 tables, the seven rating cases and
the outcome cases) live in the same files under keys that this script never
overwrites. Run: python scripts/gen_golden.py  (from backend/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import SHARED_DIR, load_game_config_file  # noqa: E402
from app.domain.damage import compute_preview  # noqa: E402
from app.domain.hand import PoolProblem, build_decks, deal_hand  # noqa: E402
from app.domain.rating import rating_delta  # noqa: E402

GOLDEN = SHARED_DIR / "golden"


def _load(name: str) -> dict:
    p = GOLDEN / name
    return json.loads(p.read_text()) if p.exists() else {}


def _save(name: str, data: dict) -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    # One top-level key per line, list items one per line, each item compact.
    parts = []
    for k, v in data.items():
        if isinstance(v, list) and v and isinstance(v[0], (list, dict)):
            items = ",\n  ".join(json.dumps(x, separators=(",", ":")) for x in v)
            parts.append(f" {json.dumps(k)}: [\n  {items}\n ]")
        else:
            parts.append(f" {json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}")
    (GOLDEN / name).write_text("{\n" + ",\n".join(parts) + "\n}\n")


def main() -> None:
    cfg = load_game_config_file()

    # damage.json: every rating pair at the seed ratings
    dmg = _load("damage.json")
    pairs = []
    for p_row in cfg.tiers:
        for q_row in cfg.tiers:
            for pr in (p_row.min_rating, p_row.seed_rating):
                pv = compute_preview(p_row.tier, q_row.tier, q_row.base_damage, q_row.base_recoil, cfg)
                pairs.append(
                    {
                        "player_rating": pr,
                        "problem_rating": q_row.seed_rating,
                        "damage": pv.damage,
                        "recoil": pv.recoil,
                        "tier_diff": pv.tier_diff,
                        "scenario": pv.scenario,
                        "crit": pv.crit,
                    }
                )
    dmg["rating_pairs"] = pairs
    _save("damage.json", dmg)

    # rating.json: the frozen grid
    rat = _load("rating.json")
    grid = []
    for wt in range(1, 6):
        for lt in range(1, 6):
            w_max = cfg.tier_row(wt).max_hp
            l_max = cfg.tier_row(lt).max_hp
            for w_pct in (5, 20, 21, 50, 80, 100):
                for l_pct in (0, 10):
                    for minutes in (10, 15, 16, 30, 31, 60, 61, 179):
                        for hits in (0, 3):
                            w_hp = w_max * w_pct // 100
                            l_hp = l_max * l_pct // 100
                            r = rating_delta(wt, lt, w_hp, w_max, l_hp, l_max, minutes * 60, hits, cfg)
                            grid.append(
                                [wt, lt, w_hp, w_max, l_hp, l_max, minutes * 60, hits, r.winner, r.loser]
                            )
    rat["grid_columns"] = [
        "w_tier", "l_tier", "w_hp", "w_max", "l_hp", "l_max", "elapsed_s", "winner_hits",
        "winner_delta", "loser_delta",
    ]
    rat["grid"] = grid
    _save("rating.json", rat)

    # hands.json
    pool = [
        PoolProblem("b1a", 1, "bit"), PoolProblem("b1b", 1, "bit"), PoolProblem("b2a", 2, "bit"),
        PoolProblem("b2b", 2, "bit"), PoolProblem("b3a", 3, "bit"), PoolProblem("b3b", 3, "bit"),
        PoolProblem("b4a", 4, "bit"), PoolProblem("b5a", 5, "bit"), PoolProblem("n1a", 1, "binary"),
        PoolProblem("n2a", 2, "binary"), PoolProblem("n3a", 3, "binary"), PoolProblem("n4a", 4, "binary"),
        PoolProblem("n5a", 5, "binary"), PoolProblem("g1a", 1, "general"), PoolProblem("g2a", 2, "general"),
        PoolProblem("g3a", 3, "general"), PoolProblem("g4a", 4, "general"),
    ]
    cases = []
    for seed in (1, 42, 987654321):
        for map_id in ("bit", "binary", "prestige"):
            for tier in (1, 2, 3, 5):
                decks, _ = build_decks(pool, seed, cfg.map_cfg(map_id), cfg)
                hand = deal_hand(decks, tier, cfg)
                cases.append(
                    {
                        "seed": seed, "map": map_id, "player_tier": tier,
                        "tiers": list(hand.tiers), "slots": list(hand.slots),
                        "decks": {str(k): v for k, v in decks.items()},
                    }
                )
    hands = _load("hands.json")
    hands["pool"] = [p.__dict__ for p in pool]
    hands["cases"] = cases
    _save("hands.json", hands)
    print(f"damage pairs={len(pairs)} rating grid={len(grid)} hand cases={len(cases)}")


if __name__ == "__main__":
    main()
