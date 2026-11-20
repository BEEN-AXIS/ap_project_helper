"""Career statistics: streaks, maps, activity and totals from finished matches."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app.models import Match
from app.services.stats import summarize
from tests.api.test_api import H, client, signup  # noqa: F401  (fixture)

ME = 7
TODAY = date(2026, 11, 20)


def _m(i: int, winner: int | None, *, me_side: int = 1, map_: str = "bit", reason: str = "ko", days_ago: int = 0,
       status: str = "finished", stats: dict | None = None, dmg: int = 1000) -> Match:
    other = 99
    p1, p2 = (ME, other) if me_side == 1 else (other, ME)
    m = Match(id=f"m{i}", mode="ranked", map=map_, seed=i, status=status, end_reason=reason,
              outcome="draw" if winner is None else "win", winner_side=winner, elapsed_ms=60_000 + i,
              created_at=datetime(2026, 11, 20, 12) - timedelta(days=days_ago, minutes=100 - i),
              player1_profile_id=p1, player2_profile_id=p2)
    st = stats or {}
    if me_side == 1:
        m.player1_stats, m.player1_damage_dealt, m.player1_hits_landed = st, dmg, 2
    else:
        m.player2_stats, m.player2_damage_dealt, m.player2_hits_landed = st, dmg, 2
    return m


def test_no_matches_gives_zeros() -> None:
    s = summarize([], ME, TODAY)
    assert s["played"] == 0 and s["win_rate"] == 0 and s["streak"] == {"kind": None, "count": 0} and s["form"] == []


def test_streaks_results_and_maps_are_from_my_side() -> None:
    rows = [
        _m(1, 1),  # W
        _m(2, 1, me_side=2),  # I am side 2, side 1 won: L
        _m(3, 2, me_side=2, map_="binary"),  # W
        _m(4, 1, map_="binary", reason="timer"),  # W (not a KO)
        _m(5, 1),  # W
        _m(6, None),  # draw is not counted in the form as W or L
        _m(7, 1, status="aborted"),  # ignored
    ]
    s = summarize(rows, ME, TODAY)
    assert (s["played"], s["wins"], s["losses"], s["draws"]) == (6, 4, 1, 1)
    assert s["form"] == ["W", "L", "W", "W", "W", "D"]
    assert s["streak"] == {"kind": None, "count": 0}  # the latest match was a draw
    assert s["best_win_streak"] == 3
    assert s["ko_wins"] == 3
    assert s["by_map"]["binary"] == {"played": 2, "wins": 2, "losses": 0}
    assert s["win_rate"] == 67


def test_current_streak_counts_back_from_the_latest() -> None:
    s = summarize([_m(1, 2), _m(2, 1), _m(3, 1), _m(4, 1)], ME, TODAY)
    assert s["streak"] == {"kind": "W", "count": 3}
    s = summarize([_m(1, 1), _m(2, 2), _m(3, 2)], ME, TODAY)
    assert s["streak"] == {"kind": "L", "count": 2}


def test_totals_best_and_activity_window() -> None:
    rows = [
        _m(1, 1, stats={"crits": 2, "backfires": 1, "biggest_hit": 9000, "fastest_solve_ms": 50_000}, dmg=12000),
        _m(2, 2, stats={"crits": 1, "biggest_hit": 4000, "fastest_solve_ms": 30_000}, dmg=3000, days_ago=3),
        _m(3, 1, days_ago=200),  # counts in totals, not in the 12-week heatmap
    ]
    s = summarize(rows, ME, TODAY)
    assert s["damage_dealt"] == 16000 and s["crits"] == 3 and s["backfires"] == 1
    assert s["biggest_hit"] == 9000 and s["fastest_solve_ms"] == 30_000
    assert sum(s["activity"].values()) == 2 and "2026-11-17" in s["activity"]


def test_profile_endpoint_includes_stats_achievements_and_collection(client: TestClient) -> None:  # noqa: F811
    tok, prof = signup(client)
    d = client.get(f"/api/profiles/{prof['display_name']}", headers=H(tok)).json()
    st = d["stats"]
    assert st["played"] == 0 and st["rank"]["position"] >= 1 and st["rank"]["of"] >= 1
    assert {a["id"] for a in st["achievements"]} >= {"flawless", "hot_streak"}
    assert not any(a["earned"] for a in st["achievements"])
    assert st["collection"]["arena"]["total"] == 10 and st["collection"]["weapon"]["owned"] >= 1
    assert st["solved"]["of"] == 17 and st["submissions"]["judged"] == 0
