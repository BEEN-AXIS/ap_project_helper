"""Profiles, settings, leaderboard, problems (practice browser) and the dojo Run."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from app.api.deps import Caller, current
from app.context import AppContext, ctx_dep
from app.core.db import run_db
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.domain import progress
from app.domain.tiers import get_tier
from app.engine.finish import today_utc
from app.models import Match, Profile, QuestProgress, RatingHistory, Submission, utcnow
from app.services.judging import run_samples
from app.services.profiles import profile_private, profile_public
from app.services.stats import player_stats

router = APIRouter(tags=["players"])


def match_brief(m: Match, me: int | None = None) -> dict:
    side = 1 if m.player1_profile_id == me else 2 if m.player2_profile_id == me else None
    return {
        "id": m.id, "mode": m.mode, "map": m.map, "status": m.status, "end_reason": m.end_reason,
        "outcome": m.outcome, "winner_side": m.winner_side, "labels": m.labels, "created_at": m.created_at.isoformat(),
        "elapsed_ms": m.elapsed_ms, "your_side": side,
        "players": [{"side": 1, "name": m.player1_name, "tier": m.player1_tier, "is_bot": m.player1_is_bot},
                    {"side": 2, "name": m.player2_name, "tier": m.player2_tier, "is_bot": m.player2_is_bot}],
        "rating_delta": ((m.result or {}).get("sides", {}).get(str(side), {}) or {}).get("delta") if side else None,
    }


def _quests(s: Session, pid: int, ctx: AppContext) -> list[dict]:
    if not ctx.cfg.feature("quests"):
        return []
    day = today_utc()
    rows = {r.key: r for r in s.exec(select(QuestProgress).where(QuestProgress.profile_id == pid, QuestProgress.day == day)).all()}
    out = []
    for q in progress.daily_quests(day, ctx.cfg):
        r = rows.get(q.id)
        out.append({"id": q.id, "target": q.target, "ap": q.ap, "progress": r.progress if r else 0,
                    "complete": bool(r and r.earned_at), "claimed": bool(r and r.claimed_at)})
    return out


@router.get("/me")
async def me(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    def work(s: Session) -> dict:
        p = s.get(Profile, caller.profile_id)
        if p is None:
            raise AppError("not_found", "Profile not found")
        recent = s.exec(select(Match).where(
            ((Match.player1_profile_id == p.id) | (Match.player2_profile_id == p.id)),
            Match.status.in_(["finished", "aborted"])).order_by(Match.created_at.desc()).limit(8)).all()  # type: ignore[attr-defined]
        d = profile_private(s, p, ctx.cfg)
        d["quests"] = _quests(s, p.id or 0, ctx)
        d["recent_matches"] = [match_brief(m, p.id) for m in recent]
        return d

    d = await run_db(work)
    d["active_match"] = ctx.matches.active_match_for(caller.profile_id)
    d["judge"] = {"backend": ctx.runner.name, "sandboxed": ctx.runner.sandboxed}
    d["queue"] = ctx.matchmaker.status(caller.profile_id)
    return d


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: dict


TEMPLATE_MAX_BYTES = 16 * 1024


@router.patch("/me/settings")
async def save_settings(body: SettingsBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    # Code templates (one per language) live here too, so the budget is generous;
    # everything else together must stay small.
    templates = body.settings.get("templates", {})
    if not isinstance(templates, dict):
        raise AppError("validation", "templates must map a language to its code")
    known = {lang.id for lang in ctx.cfg.languages}
    for lang, code in templates.items():
        if lang not in known:
            raise AppError("validation", f"Unknown language {lang!r} in templates")
        if not isinstance(code, str) or len(code.encode()) > TEMPLATE_MAX_BYTES:
            raise AppError("validation", "Each template must be text under 16 KB")
    rest = {k: v for k, v in body.settings.items() if k != "templates"}
    if len(json.dumps(rest)) > 4096:
        raise AppError("validation", "Settings are too large")

    def work(s: Session) -> dict:
        p = s.get(Profile, caller.profile_id)
        assert p is not None
        p.settings = body.settings
        s.add(p)
        return p.settings

    return {"settings": await run_db(work)}


@router.post("/quests/{quest_id}/claim")
async def claim_quest(quest_id: str, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    day = today_utc()
    q = next((q for q in progress.daily_quests(day, ctx.cfg) if q.id == quest_id), None)
    if q is None:
        raise AppError("not_found", "That quest is not active today")

    def work(s: Session) -> dict:
        r = s.exec(select(QuestProgress).where(QuestProgress.profile_id == caller.profile_id, QuestProgress.day == day,
                                               QuestProgress.key == quest_id)).first()
        if r is None or r.earned_at is None:
            raise AppError("conflict", "Quest not complete yet")
        if r.claimed_at is not None:
            raise AppError("conflict", "Already claimed")
        p = s.get(Profile, caller.profile_id)
        assert p is not None
        r.claimed_at = utcnow()
        p.points += q.ap
        s.add(r)
        s.add(p)
        unlocked: list[str] = []
        try:
            from app.skins.service import evaluate_unlocks

            unlocked = evaluate_unlocks(s, p, ctx.cfg)
        except ImportError:
            pass
        return {"ap": q.ap, "points": p.points, "unlocked": unlocked}

    return await run_db(work)


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/reports")
async def report(body: ReportBody, caller: Caller = Depends(current)) -> dict:
    from app.models import Report

    def work(s: Session) -> dict:
        m = s.get(Match, body.match_id) if body.match_id else None
        target = None
        if m is not None:
            target = m.player2_profile_id if m.player1_profile_id == caller.profile_id else m.player1_profile_id
        s.add(Report(reporter_id=caller.profile_id, match_id=body.match_id, target_profile_id=target, reason=body.reason))
        return {"ok": True}

    return await run_db(work)


@router.get("/quests")
async def quests(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return {"day": today_utc(), "quests": await run_db(lambda s: _quests(s, caller.profile_id, ctx))}


@router.get("/profiles/{username}")
async def public_profile(username: str, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    def work(s: Session) -> dict:
        p = s.exec(select(Profile).where(func.lower(Profile.display_name) == username.lower(), Profile.is_bot == False)).first()  # noqa: E712
        if p is None:
            raise AppError("not_found", "No such player")
        hist = s.exec(select(RatingHistory).where(RatingHistory.profile_id == p.id, RatingHistory.voided == False)  # noqa: E712
                      .order_by(RatingHistory.created_at.desc()).limit(50)).all()  # type: ignore[attr-defined]
        matches = s.exec(select(Match).where(((Match.player1_profile_id == p.id) | (Match.player2_profile_id == p.id)),
                                             Match.status.in_(["finished", "aborted"]))  # type: ignore[attr-defined]
                         .order_by(Match.created_at.desc()).limit(20)).all()  # type: ignore[attr-defined]
        accepted = s.exec(select(func.count()).select_from(Submission).where(Submission.profile_id == p.id, Submission.verdict == "AC")).one()
        total = s.exec(select(func.count()).select_from(Submission).where(Submission.profile_id == p.id, Submission.status == "done")).one()
        d = profile_public(p, ctx.cfg)
        d["rating_history"] = [{"match_id": h.match_id, "before": h.before, "after": h.after, "delta": h.delta,
                                "at": h.created_at.isoformat()} for h in reversed(hist)]
        d["matches"] = [match_brief(m, p.id) for m in matches]
        d["accuracy"] = {"accepted": accepted, "judged": total}
        d["stats"] = player_stats(s, p, ctx.cfg, ctx.problems.by_id)
        return d

    return await run_db(work)


# People on the boards: profiles with a login (bots and the practice dummy have none).
_PEOPLE = (Profile.is_bot == False, Profile.user_id != None)  # noqa: E711, E712


def _board_row(rank: int, pid: int, name: str, rating: int, score: int, wins: int, losses: int, ctx: AppContext) -> dict:
    return {"rank": rank, "profile_id": pid, "name": name, "rating": rating, "tier": get_tier(rating, ctx.cfg),
            "score": score, "wins": wins, "losses": losses}


def _board(s: Session, scope: str, map: str | None, ctx: AppContext) -> list[dict]:
    """The ranked rows of one board. All-time is the top 100, read in order from
    ix_profiles_ladder; the weekly and map boards add up every finished match."""
    if scope == "all" and not map:
        top = s.exec(select(Profile).where(*_PEOPLE)
                     .order_by(Profile.rating.desc(), func.lower(Profile.display_name)).limit(100)).all()  # type: ignore[attr-defined]
        return [_board_row(i, p.id or 0, p.display_name, p.rating, p.rating, p.wins, p.losses, ctx)
                for i, p in enumerate(top, 1)]
    people = {r[0]: r for r in s.exec(select(Profile.id, Profile.display_name, Profile.rating, Profile.wins,  # type: ignore[call-overload]
                                                Profile.losses).where(*_PEOPLE)).all()}
    since = utcnow() - timedelta(days=7) if scope == "week" else None
    score: dict[int, int] = {}
    if map:   # wins on the map (ix_matches_map_winners)
        wins = select(Match.winner_side, Match.player1_profile_id, Match.player2_profile_id).where(
            Match.status == "finished", Match.map == map, Match.winner_side != None)  # noqa: E711
        if since:
            wins = wins.where(Match.end_time >= since)  # type: ignore[operator]
        for side, p1, p2 in s.exec(wins).all():
            wid = p1 if side == 1 else p2
            if wid in people:
                score[wid] = score.get(wid, 0) + 1
    else:     # rating gained this week (ix_matches_finished_end_time)
        gains = select(Match.player1_profile_id, Match.player2_profile_id, Match.result).where(
            Match.status == "finished", Match.end_time >= since)  # type: ignore[operator]
        for p1, p2, result in s.exec(gains).all():
            for n, pid in (("1", p1), ("2", p2)):
                blk = (result or {}).get("sides", {}).get(n)
                if blk and pid in people:
                    score[pid] = score.get(pid, 0) + int(blk.get("delta", 0))
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], people[kv[0]][1].lower()))
    return [_board_row(i, pid, people[pid][1], people[pid][2], sc, people[pid][3], people[pid][4], ctx)
            for i, (pid, sc) in enumerate(ranked, 1)]


def _ladder_place(s: Session, profile_id: int, ctx: AppContext) -> dict | None:
    """A player's own row on the all-time board when they are outside the top 100:
    their rank is one more than the people ordered ahead of them."""
    p = s.get(Profile, profile_id)
    if p is None or p.is_bot or p.user_id is None:
        return None
    ahead = s.exec(select(func.count()).select_from(Profile).where(
        *_PEOPLE, or_(Profile.rating > p.rating,  # type: ignore[arg-type]
                      and_(Profile.rating == p.rating, func.lower(Profile.display_name) < func.lower(p.display_name))))).one()  # type: ignore[arg-type]
    return _board_row(int(ahead) + 1, p.id or 0, p.display_name, p.rating, p.rating, p.wins, p.losses, ctx)


@router.get("/leaderboard")
async def leaderboard(scope: Literal["all", "week"] = "all", map: str | None = Query(default=None, max_length=16),
                      caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    key = f"lb:{scope}:{map}"
    hit = ctx.cache.get(key)
    if hit and time.monotonic() - hit[0] < 30:
        rows = hit[1]
    else:
        rows = await run_db(lambda s: _board(s, scope, map, ctx))
        ctx.cache[key] = (time.monotonic(), rows)
    mine = next((r for r in rows if r["profile_id"] == caller.profile_id), None)
    if mine is None and scope == "all" and not map:
        mine = await run_db(lambda s: _ladder_place(s, caller.profile_id, ctx))
    return {"scope": scope, "map": map, "rows": rows[:100], "me": mine,
            "metric": "rating" if scope == "all" and not map else ("wins" if map else "rating_gained")}


# Problems (practice browser) ------------------------------------------------


@router.get("/problems")
async def list_problems(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    def solved(s: Session) -> set[int]:
        return set(s.exec(select(Submission.problem_id).where(Submission.profile_id == caller.profile_id,
                                                             Submission.verdict == "AC")).all())

    done = await run_db(solved)
    items = sorted(ctx.problems.by_slug.values(), key=lambda p: (p.biome, p.tier, p.slug))
    return {"problems": [{**p.summary(), "solved": p.id in done} for p in items]}


@router.get("/problems/{slug}")
async def get_problem(slug: str, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    p = ctx.problems.get(slug)
    if p is None:
        raise AppError("not_found", "No such problem")
    return p.public()


class DojoRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(default="python", max_length=16)
    code: str = Field(max_length=70000)
    input: str | None = Field(default=None, max_length=70000)


@router.post("/problems/{slug}/run")
async def dojo_run(slug: str, body: DojoRunBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    p = ctx.problems.get(slug)
    if p is None:
        raise AppError("not_found", "No such problem")
    enforce(f"run:{caller.profile_id}", ctx.cfg.rate_limits.run)
    if caller.profile_id in ctx.runs_inflight:
        raise AppError("busy", "A Run is already in progress")
    ctx.runs_inflight.add(caller.profile_id)
    try:
        return await run_samples(ctx.pool, ctx.cfg, p, body.language, body.code, body.input, practice=True)
    finally:
        ctx.runs_inflight.discard(caller.profile_id)
