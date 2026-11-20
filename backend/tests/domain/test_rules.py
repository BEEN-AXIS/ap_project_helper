"""Phase 1 gate: tiers, damage, hands, outcomes and rating against the golden vectors."""

from __future__ import annotations

import ast
import inspect
import json
import math
from pathlib import Path

import pytest

from app.core.config import SHARED_DIR, load_game_config_file
from app.domain import damage, hand, outcome, powerups, rating, tiers
from app.domain.damage import compute_preview, damage_class
from app.domain.gameconfig import GameConfig
from app.domain.hand import PoolProblem, build_decks, consume_slot, deal_hand, fill_slot, hand_window, reroll_slot
from app.domain.outcome import SideEnd, classify
from app.domain.rating import apply_daily_cap, apply_rating, rating_delta, scale_delta, speed_bracket

CFG = load_game_config_file()
GOLDEN = SHARED_DIR / "golden"


def golden(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


# Tiers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating_value,tier",
    [(0, 1), (800, 1), (1199, 1), (1200, 2), (1399, 2), (1400, 3), (1599, 3), (1600, 4), (1899, 4), (1900, 5), (3500, 5)],
)
def test_get_tier_thresholds(rating_value: int, tier: int) -> None:
    assert tiers.get_tier(rating_value, CFG) == tier


def test_seed_ratings_sit_inside_their_tier() -> None:
    for row in CFG.tiers:
        assert tiers.get_tier(row.seed_rating, CFG) == row.tier


def test_max_hp_follows_rating() -> None:
    assert tiers.max_hp_for_rating(1200, CFG) == 28000
    assert tiers.max_hp_for_rating(2100, CFG) == 180000


# Damage -----------------------------------------------------------------------

DMG = golden("damage.json")


@pytest.mark.parametrize("attacker", range(1, 6))
@pytest.mark.parametrize("problem", range(1, 6))
def test_damage_and_recoil_grids(attacker: int, problem: int) -> None:
    row = CFG.tier_row(problem)
    pv = compute_preview(attacker, problem, row.base_damage, row.base_recoil, CFG)
    assert pv.damage == DMG["grid_damage"][attacker - 1][problem - 1]
    assert pv.recoil == DMG["grid_recoil"][attacker - 1][problem - 1]


@pytest.mark.parametrize("attacker", range(1, 6))
@pytest.mark.parametrize("problem", range(1, 6))
def test_derived_balance_tables(attacker: int, problem: int) -> None:
    row = CFG.tier_row(problem)
    pv = compute_preview(attacker, problem, row.base_damage, row.base_recoil, CFG)
    own_max = CFG.tier_row(attacker).max_hp
    share = f"{round(pv.recoil * 100 / own_max + 1e-9, 1):.1f}"
    assert share == DMG["recoil_share_pct_1dp"][attacker - 1][problem - 1]
    assert math.ceil(own_max / pv.damage) == DMG["hits_to_kill_same_tier"][attacker - 1][problem - 1]
    assert math.ceil(50000 / pv.damage) == DMG["hits_to_kill_specialist"][attacker - 1][problem - 1]


def test_damage_anchors_from_the_chat() -> None:
    for a in DMG["anchors"]:
        row = CFG.tier_row(a["problem_tier"])
        pv = compute_preview(a["player_tier"], a["problem_tier"], row.base_damage, row.base_recoil, CFG)
        assert (pv.damage, pv.recoil) == (a["damage"], a["recoil"])


def test_rating_pairs_vector() -> None:
    for p in DMG["rating_pairs"]:
        pt = tiers.get_tier(p["player_rating"], CFG)
        qt = tiers.get_tier(p["problem_rating"], CFG)
        row = CFG.tier_row(qt)
        pv = compute_preview(pt, qt, row.base_damage, row.base_recoil, CFG)
        assert (pv.damage, pv.recoil, pv.tier_diff, pv.scenario, pv.crit) == (
            p["damage"], p["recoil"], p["tier_diff"], p["scenario"], p["crit"]
        )


def test_damage_classes_vector() -> None:
    for c in DMG["damage_classes"]:
        assert damage_class(c["amount"], c["max_hp"], CFG) == c["class"]


def test_crit_is_tier_diff_minus_two_or_lower() -> None:
    assert [damage.is_crit(d, CFG) for d in range(-4, 5)] == [True, True, True] + [False] * 6


def test_scenarios_cover_every_tier_diff() -> None:
    names = [damage.scenario_name(d, CFG) for d in range(-4, 5)]
    assert names == ["heroic", "brave", "ambitious", "stretching", "on_level", "safe", "lazy", "cowardly", "pathetic"]


def test_rules_functions_never_accept_a_skin() -> None:
    """Skins never change a number: damage, recoil, HP and rating take no skin id."""
    fns = [
        damage.compute_preview, damage.multiplier_pcts, damage.damage_class, damage.apply_hp_loss,
        rating.rating_delta, rating.scale_delta, rating.apply_rating, tiers.get_tier, tiers.max_hp_for_rating,
    ]
    for fn in fns:
        params = [p.lower() for p in inspect.signature(fn).parameters]
        assert not any("skin" in p or "cosmetic" in p or "equipped" in p for p in params), fn.__name__


def test_hp_floor() -> None:
    assert damage.apply_hp_loss(1000, 5000) == 0
    assert damage.apply_hp_loss(10000, 4000) == 6000


# Rating -----------------------------------------------------------------------

RAT = golden("rating.json")


@pytest.mark.parametrize("case", RAT["cases"], ids=[c["name"] for c in RAT["cases"]])
def test_seven_golden_rating_cases(case: dict) -> None:
    r = rating_delta(
        case["w_tier"], case["l_tier"], case["w_hp"], case["w_max"], case["l_hp"], case["l_max"],
        case["minutes"] * 60, case["winner_hits"], CFG,
    )
    assert (r.winner, r.loser) == (case["winner"], case["loser"])
    assert [s[0] for s in r.steps] == case["labels"]


def test_rating_grid_snapshot() -> None:
    for row in RAT["grid"]:
        wt, lt, w_hp, w_max, l_hp, l_max, el, hits, w_exp, l_exp = row
        r = rating_delta(wt, lt, w_hp, w_max, l_hp, l_max, el, hits, CFG)
        assert (r.winner, r.loser) == (w_exp, l_exp), row


def _all_inputs():
    for wt in range(1, 6):
        for lt in range(1, 6):
            w_max, l_max = CFG.tier_row(wt).max_hp, CFG.tier_row(lt).max_hp
            for w_pct in range(1, 101, 3):
                for l_pct in (0, 5, 19, 20, 21, 60):
                    for el in (60, 900, 901, 1800, 1801, 3600, 3601, 10800):
                        for hits in (0, 1, 7):
                            yield wt, lt, w_max * w_pct // 100 or 1, w_max, l_max * l_pct // 100, l_max, el, hits


def test_property_hollow_winner_always_zero() -> None:
    for args in _all_inputs():
        if args[7] == 0:
            assert rating_delta(*args, CFG).winner == 0


def test_property_underdog_never_gets_narrow_win_penalty() -> None:
    for args in _all_inputs():
        if args[0] < args[1]:
            labels = [s[0] for s in rating_delta(*args, CFG).steps]
            assert "narrow_win" not in labels


def test_property_speed_bonus_never_negative_and_loser_unaffected_by_speed() -> None:
    for args in _all_inputs():
        r = rating_delta(*args, CFG)
        for label, w, l_ in r.steps:
            if label in ("blitz", "fast", "standard"):
                assert w > 0 and l_ == 0


def test_property_ratings_never_below_floor() -> None:
    for start in (0, 10, 49, 50, 800, 1200):
        for args in _all_inputs():
            r = rating_delta(*args, CFG)
            assert apply_rating(start, r.loser, CFG) >= 0
            assert apply_rating(start, r.winner, CFG) >= 0


def test_hypothesis_properties_if_installed() -> None:
    hyp = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")

    @hyp.given(
        wt=st.integers(1, 5), lt=st.integers(1, 5), w=st.integers(1, 100), l_=st.integers(0, 100),
        el=st.integers(0, 20000), hits=st.integers(0, 50), start=st.integers(0, 4000),
    )
    def prop(wt, lt, w, l_, el, hits, start):
        w_max, l_max = CFG.tier_row(wt).max_hp, CFG.tier_row(lt).max_hp
        r = rating_delta(wt, lt, w_max * w // 100 or 1, w_max, l_max * l_ // 100, l_max, el, hits, CFG)
        if hits == 0:
            assert r.winner == 0
        if wt < lt:
            assert "narrow_win" not in [s[0] for s in r.steps]
        assert apply_rating(start, r.loser, CFG) >= 0

    prop()


def test_speed_brackets() -> None:
    assert [speed_bracket(s, CFG) for s in (0, 900, 901, 1800, 1801, 3600, 3601)] == [
        "blitz", "blitz", "fast", "fast", "standard", "standard", "methodical"
    ]


def test_multipliers_round_toward_zero_and_cap_gains_only() -> None:
    assert scale_delta(75, 50) == 37
    assert scale_delta(-75, 50) == -37
    assert scale_delta(-1, 50) == 0
    assert apply_daily_cap(60, 70, 100) == 30
    assert apply_daily_cap(60, 120, 100) == 0
    assert apply_daily_cap(-60, 500, 100) == -60
    assert rating.mode_pct("bot", True, CFG) == 50
    assert rating.mode_pct("practice", True, CFG) == 0
    assert rating.rematch_pct(0, CFG) == 100 and rating.rematch_pct(1, CFG) == 50 and rating.rematch_pct(5, CFG) == 25


# Hands ------------------------------------------------------------------------

HANDS = golden("hands.json")
POOL = [PoolProblem(**p) for p in HANDS["pool"]]


def test_hand_window() -> None:
    assert [hand_window(t, CFG) for t in range(1, 6)] == [[1, 2, 3, 4], [1, 2, 3, 4], [2, 3, 4, 5], [2, 3, 4, 5], [2, 3, 4, 5]]


@pytest.mark.parametrize("case", HANDS["cases"], ids=lambda c: f"{c['seed']}-{c['map']}-t{c['player_tier']}")
def test_hand_golden_vectors(case: dict) -> None:
    decks, _ = build_decks(POOL, case["seed"], CFG.map_cfg(case["map"]), CFG)
    assert {str(k): v for k, v in decks.items()} == case["decks"]
    h = deal_hand(decks, case["player_tier"], CFG)
    assert list(h.tiers) == case["tiers"]
    assert list(h.slots) == case["slots"]


def test_every_hand_has_four_different_tiers_and_both_players_match() -> None:
    for seed in range(200):
        for map_id in ("bit", "binary", "prestige"):
            decks, _ = build_decks(POOL, seed, CFG.map_cfg(map_id), CFG)
            for t in range(1, 6):
                a = deal_hand(decks, t, CFG)
                b = deal_hand(decks, t, CFG)
                assert len(set(a.tiers)) == 4
                assert a.slots == b.slots
                assert all(s is not None for s in a.slots)


def test_map_filters_pool_and_falls_back() -> None:
    decks, warnings = build_decks(POOL, 7, CFG.map_cfg("binary"), CFG)
    for tier, deck in decks.items():
        assert deck[0].startswith("n")  # the binary problem of each tier comes first
    assert warnings  # binary has one problem per tier, below min_deck_per_tier


def test_consume_redeal_and_reroll() -> None:
    decks, _ = build_decks(POOL, 3, CFG.map_cfg("bit"), CFG)
    h = deal_hand(decks, 1, CFG)
    first = h.slots[0]
    h2 = consume_slot(h, 0)
    assert h2.slots[0] is None and first in h2.solved
    h3 = fill_slot(h2, decks, 0)
    assert h3.slots[0] not in (None, first)  # next problem of that tier, not the solved one
    h4 = reroll_slot(h3, decks, 1)
    assert h4.slots[1] != h3.slots[1]
    assert h4.tiers == h.tiers


def test_draw_skips_solved_then_allows_repeats() -> None:
    decks = {1: ["a", "b"], 2: ["c"], 3: ["d"], 4: ["e"], 5: []}
    h = deal_hand(decks, 1, CFG)
    assert h.slots[0] == "a"
    h = fill_slot(consume_slot(h, 0), decks, 0)
    assert h.slots[0] == "b"
    h = fill_slot(consume_slot(h, 0), decks, 0)
    assert h.slots[0] in ("a", "b")  # everything solved: repeats are allowed
    roundtrip = hand.HandState.from_json(json.loads(json.dumps(h.to_json())))
    assert roundtrip == h


# Outcomes ---------------------------------------------------------------------


@pytest.mark.parametrize("case", golden("outcomes.json")["cases"], ids=lambda c: c["name"])
def test_outcome_vectors(case: dict) -> None:
    o = classify(case["end_reason"], SideEnd(**case["p1"]), SideEnd(**case["p2"]))
    assert o.outcome == case["outcome"]
    assert o.winner_side == case["winner_side"]
    assert {str(k): v for k, v in o.labels.items()} == case["labels"]


# Powerups ---------------------------------------------------------------------


def test_powerups() -> None:
    assert powerups.initial_charges("ranked", CFG) == (1, 2)
    assert powerups.initial_charges("practice", CFG) == (0, -1)
    until = powerups.shield_until(1000, CFG)
    assert powerups.shield_active(until, 20999) and not powerups.shield_active(until, 21000)
    assert [powerups.next_hint_level(n, CFG) for n in range(4)] == [1, 2, 3, None]
    assert powerups.spend(-1) == -1 and powerups.has_charge(-1)
    assert powerups.spend(1) == 0 and not powerups.has_charge(0)


# Config -----------------------------------------------------------------------


def test_config_validates_and_rejects_bad_files() -> None:
    raw = json.loads((SHARED_DIR / "game-config.json").read_text())
    GameConfig.model_validate(raw)
    bad = dict(raw, unknown_key=1)
    with pytest.raises(Exception):
        GameConfig.model_validate(bad)
    bad2 = json.loads(json.dumps(raw))
    bad2["tiers"][1]["min_rating"] = 5000
    with pytest.raises(Exception):
        GameConfig.model_validate(bad2)


# Purity -----------------------------------------------------------------------

FORBIDDEN = {"sqlmodel", "sqlalchemy", "fastapi", "time", "socket", "os", "subprocess", "asyncio", "requests", "httpx", "app.core", "app.models"}


def test_domain_package_has_no_io_clock_or_db_imports() -> None:
    domain_dir = Path(outcome.__file__).parent
    for py in domain_dir.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in FORBIDDEN and n not in FORBIDDEN, f"{py.name} imports {n}"
            if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow", "time"):
                if isinstance(node.value, ast.Name) and node.value.id in ("datetime", "time"):
                    raise AssertionError(f"{py.name} reads the clock")


def test_difficulty_level_is_the_cards_place_in_the_hand_window() -> None:
    """0 easy .. 3 tough. It only picks the animation; damage still comes from tier_diff."""
    from app.domain.hand import difficulty_level, hand_window

    cfg = load_game_config_file()
    for player_tier in range(1, 6):
        window = hand_window(player_tier, cfg)
        assert [difficulty_level(player_tier, t, cfg) for t in window] == [0, 1, 2, 3]
    assert difficulty_level(1, 1, cfg) == 0 and difficulty_level(1, 4, cfg) == 3
    assert difficulty_level(5, 2, cfg) == 0 and difficulty_level(5, 5, cfg) == 3
    assert difficulty_level(3, 1, cfg) == 0  # below the window clamps to easy
    assert cfg.hand.levels == ["easy", "normal", "medium", "tough"]
