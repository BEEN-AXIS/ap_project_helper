"""Career statistics for the home page and profiles: streaks, damage, solves,
maps, activity, achievements and the collection. `summarize` is pure (it takes
rows, not a session) so it is tested without a database; `player_stats` runs
the queries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.domain.gameconfig import GameConfig
from app.models import Achievement, Inventory, Match, Profile, Submission
from app.skins.registry import KINDS, load_registry

ACTIVITY_DAYS = 84  # twelve weeks for the heatmap


def _side(m: Match, pid: int) -> int | None:
    return 1 if m.player1_profile_id == pid else 2 if m.player2_profile_id == pid else None


def _result(m: Match, side: int) -> str:
    """W, L or D from one side's point of view (aborted matches are left out before this)."""
    if m.outcome == "draw" or m.winner_side is None:
        return "D"
    return "W" if m.winner_side == side else "L"


def summarize(matches: Iterable[Match], pid: int, today: date | None = None) -> dict[str, Any]:
    """Aggregate finished matches (any order) for one profile."""
    rows = sorted((m for m in matches if m.status == "finished" and _side(m, pid)), key=lambda m: m.created_at)
    today = today or datetime.now(UTC).date()
    results: list[str] = []
    by_map: dict[str, dict[str, int]] = {}
    by_mode: Counter[str] = Counter()
    activity: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    biggest = 0
    fastest: int | None = None
    ko_wins = 0
    elapsed: list[int] = []
    for m in rows:
        side = _side(m, pid) or 1
        r = _result(m, side)
        results.append(r)
        mp = by_map.setdefault(m.map, {"played": 0, "wins": 0, "losses": 0})
        mp["played"] += 1
        mp["wins"] += r == "W"
        mp["losses"] += r == "L"
        by_mode[m.mode] += 1
        day = m.created_at.date()
        if (today - day).days < ACTIVITY_DAYS:
            activity[day.isoformat()] += 1
        st = (m.player1_stats if side == 1 else m.player2_stats) or {}
        totals["damage_dealt"] += m.player1_damage_dealt if side == 1 else m.player2_damage_dealt
        totals["hits_landed"] += m.player1_hits_landed if side == 1 else m.player2_hits_landed
        for k in ("crits", "backfires", "blocks_absorbed", "accepted", "submissions", "hints_used", "damage_taken"):
            totals[k] += int(st.get(k, 0) or 0)
        biggest = max(biggest, int(st.get("biggest_hit", 0) or 0))
        fs = st.get("fastest_solve_ms")
        if fs:
            fastest = int(fs) if fastest is None else min(fastest, int(fs))
        if r == "W" and m.end_reason == "ko":
            ko_wins += 1
        if m.elapsed_ms:
            elapsed.append(m.elapsed_ms)
    # streaks: the current run (from the latest match back) and the best winning run
    kind: str | None = None
    count = 0
    for r in reversed(results):
        if r == "D" or kind not in (None, r):
            break
        kind, count = r, count + 1
    best = run = 0
    for r in results:
        run = run + 1 if r == "W" else 0
        best = max(best, run)
    played = len(results)
    wins = results.count("W")
    return {
        "played": played,
        "wins": wins,
        "losses": results.count("L"),
        "draws": results.count("D"),
        "win_rate": round(100 * wins / played) if played else 0,
        "streak": {"kind": kind, "count": count},
        "best_win_streak": best,
        "form": results[-10:],
        "ko_wins": ko_wins,
        "damage_dealt": totals["damage_dealt"],
        "damage_taken": totals["damage_taken"],
        "hits_landed": totals["hits_landed"],
        "crits": totals["crits"],
        "backfires": totals["backfires"],
        "blocks_absorbed": totals["blocks_absorbed"],
        "hints_used": totals["hints_used"],
        "biggest_hit": biggest,
        "fastest_solve_ms": fastest,
        "avg_match_ms": round(sum(elapsed) / len(elapsed)) if elapsed else 0,
        "by_map": by_map,
        "by_mode": dict(by_mode),
        "activity": dict(sorted(activity.items())),
    }


def player_stats(s: Session, p: Profile, cfg: GameConfig, problems_by_id: dict[int, Any]) -> dict[str, Any]:
    pid = p.id or 0
    matches = s.exec(select(Match).where(((Match.player1_profile_id == pid) | (Match.player2_profile_id == pid)),
                                         Match.status == "finished")
                     .order_by(Match.created_at.desc()).limit(1000)).all()  # type: ignore[attr-defined]
    out = summarize(matches, pid)

    # submissions: languages, verdicts and distinct problems solved
    subs = s.exec(select(Submission.language, Submission.verdict, Submission.problem_id)
                  .where(Submission.profile_id == pid, Submission.status == "done")).all()
    langs: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    solved: set[int] = set()
    for lang, verdict, prob in subs:
        langs[lang] += 1
        verdicts[verdict or "?"] += 1
        if verdict == "AC":
            solved.add(prob)
    by_biome: Counter[str] = Counter()
    by_tier: Counter[int] = Counter()
    for prob_id in solved:
        cp = problems_by_id.get(prob_id)
        if cp:
            by_biome[cp.biome] += 1
            by_tier[cp.tier] += 1
    out["submissions"] = {"judged": len(subs), "accepted": verdicts.get("AC", 0), "by_language": dict(langs),
                          "by_verdict": dict(verdicts)}
    out["solved"] = {"count": len(solved), "of": len(problems_by_id), "by_biome": dict(by_biome),
                     "by_tier": {str(k): v for k, v in sorted(by_tier.items())}}

    # achievements: every one, earned or not
    earned = {a.key: a.earned_at for a in s.exec(select(Achievement).where(Achievement.profile_id == pid)).all()}
    badges = set(p.badges or [])
    counters = p.counters or {}
    progress = {"wall": counters.get("career_blocks", 0), "bit_master": counters.get("bit_wins", 0),
                "perfectionist": counters.get("ac_streak", 0), "hot_streak": counters.get("ranked_win_streak", 0)}
    out["achievements"] = []
    for a in cfg.achievements:
        at = earned.get(a.id)
        out["achievements"].append({"id": a.id, "reward": a.reward, "target": a.target,
                                    "earned": a.id in earned or a.id in badges,
                                    "earned_at": at.isoformat() if at else None, "progress": progress.get(a.id)})

    # the collection: owned out of available, per kind
    reg = load_registry()
    owned = set(s.exec(select(Inventory.skin_id).where(Inventory.profile_id == pid)).all())
    out["collection"] = {k: {"owned": sum(1 for sid, m in reg.items() if m["kind"] == k and sid in owned),
                             "total": sum(1 for m in reg.values() if m["kind"] == k)} for k in KINDS}

    # rank by rating among people (not bots)
    above = s.exec(select(func.count()).select_from(Profile).where(Profile.is_bot == False, Profile.user_id != None,  # noqa: E711, E712
                                                                   Profile.rating > p.rating)).one()
    players = s.exec(select(func.count()).select_from(Profile).where(Profile.is_bot == False, Profile.user_id != None)).one()  # noqa: E711, E712
    out["rank"] = {"position": int(above) + 1, "of": int(players)}
    out["member_since"] = p.created_at.isoformat()
    out["since"] = (datetime.now(UTC).date() - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    return out
