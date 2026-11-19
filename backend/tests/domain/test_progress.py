from __future__ import annotations

from app.core.config import load_game_config_file
from app.domain.progress import Counters, SideSummary, achievements_earned, compute_ap, daily_quests, quest_increment, update_counters

CFG = load_game_config_file()


def summary(**kw) -> SideSummary:
    base = dict(mode="ranked", map="bit", label="victory", end_reason="ko")
    base.update(kw)
    return SideSummary(**base)  # type: ignore[arg-type]


def test_ap_ranked_win() -> None:
    total, lines = compute_ap(summary(hits_landed=4, flawless=True, blitz=True, max_streak=3), True, 0, CFG)
    assert dict(lines) == {"match": 10, "win": 20, "hits": 8, "flawless": 10, "blitz": 10, "first_win_of_day": 25, "streak": 4}
    assert total == 87


def test_ap_hit_cap_and_draw() -> None:
    total, lines = compute_ap(summary(label="draw", hits_landed=30), False, 0, CFG)
    assert dict(lines) == {"match": 10, "draw": 5, "hits": 20}


def test_ap_bot_is_half_and_capped() -> None:
    total, _ = compute_ap(summary(mode="bot", hits_landed=2), False, 0, CFG)
    assert total == (10 // 2) + (20 // 2) + (4 // 2)
    total2, lines2 = compute_ap(summary(mode="bot", hits_landed=2), False, 145, CFG)
    assert total2 == 5 and ("daily_cap", 0) in lines2


def test_practice_and_aborted_pay_nothing() -> None:
    assert compute_ap(summary(mode="practice", hits_landed=5), True, 0, CFG) == (0, [])
    assert compute_ap(summary(label=None, end_reason="aborted"), True, 0, CFG) == (0, [])


def test_daily_quests_are_seeded_by_date() -> None:
    a = [q.id for q in daily_quests("2026-11-20", CFG)]
    assert a == [q.id for q in daily_quests("2026-11-20", CFG)]
    assert len(a) == 3 and len(set(a)) == 3
    days = {tuple(q.id for q in daily_quests(f"2026-11-{d:02d}", CFG)) for d in range(1, 29)}
    assert len(days) > 3


def test_quest_increments() -> None:
    qs = {q.id: q for q in CFG.quests}
    s = summary(hits_landed=2, hits_stretching=1, blocks_absorbed=1, backfires=0)
    assert quest_increment(qs["first_blood"], s) == 2
    assert quest_increment(qs["bit_hunter"], s) == 1
    assert quest_increment(qs["binary_hunter"], s) == 0
    assert quest_increment(qs["clean_sweep"], s) == 1
    assert quest_increment(qs["daily_grind"], summary(mode="practice")) == 0


def test_achievements() -> None:
    s = summary(crits=5, heroic_hits=1, flawless=True, lowest_hp=1000, max_hp=28000, accepted=3)
    c = update_counters(Counters(), s)
    got = achievements_earned(s, c, set(), CFG)
    assert {"crit_machine", "heroic", "flawless", "comeback"} <= set(got)
    assert "crit_machine" not in achievements_earned(s, c, {"crit_machine"}, CFG)
    c2 = Counters(ac_streak=8)
    c3 = update_counters(c2, summary(accepted=2))
    assert c3.ac_streak == 10 and "perfectionist" in achievements_earned(summary(accepted=2), c3, set(), CFG)
    c4 = update_counters(c3, summary(accepted=1, failed_any=True, accepted_run_after=0))
    assert c4.ac_streak == 0
