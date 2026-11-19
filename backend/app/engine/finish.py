"""End-of-match writes, all inside the transaction that closes the match:
rating (section 5), profile stats, rating_history, Arena Points, quests,
achievements and skin unlocks. Practice matches change none of it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.domain import progress
from app.domain.gameconfig import GameConfig
from app.domain.outcome import Outcome
from app.domain.rating import apply_daily_cap, apply_rating, mode_pct, rating_delta, rematch_pct, scale_delta, speed_bracket
from app.domain.tiers import get_tier
from app.models import Achievement, Match, Profile, QuestProgress, RatingHistory, Side, utcnow


def today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _roll_day(p: Profile, day: str) -> None:
    if p.daily_day != day:
        p.daily_day = day
        p.bot_gain_today = 0
        p.casual_ap_today = 0


def apply_strikes(s: Session, profile_ids: list[int], cfg: GameConfig) -> None:
    for pid in profile_ids:
        p = s.get(Profile, pid)
        if p is None:
            continue
        p.no_show_strikes += 1
        if p.no_show_strikes >= cfg.match.no_show_strikes:
            p.queue_ban_until = utcnow() + timedelta(minutes=cfg.match.no_show_ban_min)
            p.no_show_strikes = 0
        s.add(p)


def _previous_meetings(s: Session, m: Match, cfg: GameConfig) -> int:
    since = utcnow() - timedelta(minutes=cfg.rating.rematch_window_min)
    a, b = m.player1_profile_id, m.player2_profile_id
    rows = s.exec(
        select(Match).where(
            Match.mode == "ranked", Match.status == "finished", Match.id != m.id, Match.end_time >= since,  # type: ignore[operator]
            ((Match.player1_profile_id == a) & (Match.player2_profile_id == b))
            | ((Match.player1_profile_id == b) & (Match.player2_profile_id == a)),
        )
    ).all()
    return len(rows)


def finish_tx(s: Session, m: Match, o: Outcome, cfg: GameConfig, payload: dict[str, Any], rewards: dict[int, dict[str, Any]]) -> None:
    day = today_utc()
    elapsed_s = m.elapsed_ms // 1000
    sides = {1: Side(m, 1), 2: Side(m, 2)}
    raw: dict[int, tuple[list[tuple[str, int, int]], int]] = {1: ([], 0), 2: ([], 0)}

    if o.outcome == "win" and o.winner_side:
        w, l_ = sides[o.winner_side], sides[3 - o.winner_side]
        r = rating_delta(w.tier, l_.tier, w.hp, w.max_hp, l_.hp, l_.max_hp, elapsed_s, w.hits_landed, cfg)
        raw[o.winner_side] = ([(lbl, wd, 0) for lbl, wd, _ in r.steps], r.winner)
        raw[3 - o.winner_side] = ([(lbl, 0, ld) for lbl, _, ld in r.steps], r.loser)
    elif o.outcome == "draw":
        raw = {1: ([("draw", 0, 0)], 0), 2: ([("draw", 0, 0)], 0)}

    rematch = 100
    if m.mode == "ranked":
        rematch = rematch_pct(_previous_meetings(s, m, cfg), cfg)

    for n, sd in sides.items():
        if sd.is_bot:
            continue
        prof = s.get(Profile, sd.profile_id)
        if prof is None:
            continue
        steps, delta_raw = raw[n]
        if m.mode == "practice":
            payload["sides"][str(n)] = {"before": prof.rating, "after": prof.rating, "delta": 0, "steps": [],
                                        "multiplier": 0, "profile_after": _profile_after(prof, cfg), "practice": True}
            rewards[n] = {"ap": 0, "lines": [], "quests": [], "achievements": [], "unlocked": []}
            continue
        _roll_day(prof, day)
        pct = mode_pct(m.mode, True, cfg) * rematch // 100
        delta = scale_delta(delta_raw, pct)
        if m.mode == "bot":
            capped = apply_daily_cap(delta, prof.bot_gain_today, cfg.rating.bot_daily_gain_cap)
            if capped != delta:
                steps = [*steps, ("daily_cap", 0, 0)]
            delta = capped
            if delta > 0:
                prof.bot_gain_today += delta
        before = prof.rating
        tier_before = get_tier(before, cfg)
        prof.rating = apply_rating(before, delta, cfg)
        prof.peak_rating = max(prof.peak_rating, prof.rating)
        label = o.labels.get(n)
        if label in ("victory", "hollow_victory"):
            prof.wins += 1
        elif label == "draw":
            prof.draws += 1
        else:
            prof.losses += 1
        tier_after = get_tier(prof.rating, cfg)
        step_rows = [{"key": lbl, "delta": (wd if n == o.winner_side else ld)} for lbl, wd, ld in steps]
        s.add(RatingHistory(profile_id=prof.id or 0, match_id=m.id, before=before, after=prof.rating,
                            delta=prof.rating - before, steps=step_rows, multiplier=pct))
        block: dict[str, Any] = {"before": before, "after": prof.rating, "delta": prof.rating - before, "raw_delta": delta_raw,
                                 "steps": step_rows, "multiplier": pct, "profile_after": _profile_after(prof, cfg)}
        if tier_after != tier_before:
            block["promotion"] = {
                "from_tier": tier_before, "to_tier": tier_after, "title": cfg.tier_row(tier_after).title,
                "old_max_hp": cfg.tier_row(tier_before).max_hp, "new_max_hp": cfg.tier_row(tier_after).max_hp,
                "direction": "up" if tier_after > tier_before else "down",
            }
        payload["sides"][str(n)] = block
        rewards[n] = _progress(s, m, n, prof, o, payload, cfg, day)
        s.add(prof)


def _profile_after(p: Profile, cfg: GameConfig) -> dict[str, int]:
    t = get_tier(p.rating, cfg)
    return {"rating": p.rating, "tier": t, "max_hp": cfg.tier_row(t).max_hp, "peak_rating": p.peak_rating}


def summary_for(m: Match, n: int, o: Outcome, payload: dict[str, Any], cfg: GameConfig) -> progress.SideSummary:
    sd = Side(m, n)
    st = sd.stats or {}
    block = payload["sides"].get(str(n), {})
    keys = [s["key"] for s in block.get("steps", [])]
    won = o.labels.get(n) in ("victory", "hollow_victory")
    return progress.SideSummary(
        mode=m.mode, map=m.map, label=o.labels.get(n), end_reason=o.end_reason,
        hits_landed=sd.hits_landed, hits_stretching=st.get("hits_stretching", 0), heroic_hits=st.get("heroic_hits", 0),
        crits=st.get("crits", 0), blocks_absorbed=st.get("blocks_absorbed", 0), backfires=st.get("backfires", 0),
        accepted=st.get("accepted", 0), submissions=st.get("submissions", 0),
        accepted_run_after=st.get("accepted_run_after", 0), failed_any=bool(st.get("failed_any", False)),
        flawless=won and "flawless" in keys,
        blitz=won and speed_bracket(m.elapsed_ms // 1000, cfg) == "blitz",
        elapsed_s=m.elapsed_ms // 1000, lowest_hp=st.get("lowest_hp", sd.hp), max_hp=sd.max_hp,
        one_shot=bool(st.get("one_shot", False)), max_streak=st.get("max_streak", 0),
    )


def _progress(s: Session, m: Match, n: int, prof: Profile, o: Outcome, payload: dict[str, Any], cfg: GameConfig, day: str) -> dict[str, Any]:
    summ = summary_for(m, n, o, payload, cfg)
    out: dict[str, Any] = {"ap": 0, "lines": [], "quests": [], "achievements": [], "unlocked": []}
    first_win = summ.won and prof.last_win_day != day
    casual = m.mode in ("bot", "friendly")
    ap, lines = progress.compute_ap(summ, first_win, prof.casual_ap_today, cfg)
    if not cfg.feature("streaks"):
        lines = [(k, v) for k, v in lines if k != "streak"]
        ap = sum(v for _, v in lines)
    prof.points += ap
    if casual:
        prof.casual_ap_today += ap
    if summ.won:
        prof.last_win_day = day
    out["ap"] = ap
    out["lines"] = [{"key": k, "ap": v} for k, v in lines]

    if cfg.feature("quests"):
        for q in progress.daily_quests(day, cfg):
            inc = progress.quest_increment(q, summ)
            row = s.exec(select(QuestProgress).where(QuestProgress.profile_id == prof.id, QuestProgress.day == day,
                                                     QuestProgress.key == q.id)).first()
            if row is None:
                row = QuestProgress(profile_id=prof.id or 0, day=day, key=q.id, progress=0, target=q.target)
            if inc and row.earned_at is None:
                row.progress = min(q.target, row.progress + inc)
                if row.progress >= q.target:
                    row.earned_at = utcnow()
                s.add(row)
                out["quests"].append({"id": q.id, "progress": row.progress, "target": q.target, "ap": q.ap,
                                      "complete": row.earned_at is not None})

    if cfg.feature("achievements"):
        counters = progress.update_counters(progress.Counters.from_json(prof.counters), summ)
        prof.counters = counters.to_json()
        have = {a.key for a in s.exec(select(Achievement).where(Achievement.profile_id == prof.id)).all()}
        for key in progress.achievements_earned(summ, counters, have, cfg):
            s.add(Achievement(profile_id=prof.id or 0, key=key, progress=1, earned_at=utcnow()))
            out["achievements"].append(key)
            prof.badges = [*(prof.badges or []), key]

    try:
        from app.skins.service import evaluate_unlocks

        out["unlocked"] = evaluate_unlocks(s, prof, cfg, earned_achievements=out["achievements"])
    except ImportError:
        pass
    return out
