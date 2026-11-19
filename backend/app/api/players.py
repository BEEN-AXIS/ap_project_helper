"""Profiles, settings, leaderboard, problems (practice browser) and the dojo Run."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
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


@router.patch("/me/settings")
async def save_settings(body: SettingsBody, caller: Caller = Depends(current)) -> dict:
    if len(json.dumps(body.settings)) > 4096:
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
        return d

    return await run_db(work)


@router.get("/leaderboard")
async def leaderboard(scope: Literal["all", "week"] = "all", map: str | None = Query(default=None, max_length=16),
                      caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    key = f"lb:{scope}:{map}"
    hit = ctx.cache.get(key)
    if hit and time.monotonic() - hit[0] < 30:
        rows = hit[1]
    else:
        def work(s: Session) -> list[dict]:
            profs = {p.id: p for p in s.exec(select(Profile).where(Profile.is_bot == False, Profile.user_id != None)).all()}  # noqa: E711, E712
            score: dict[int, int] = {}
            if scope == "all" and not map:
                score = {pid: p.rating for pid, p in profs.items()}
            else:
                since = utcnow() - timedelta(days=7) if scope == "week" else None
                q = select(Match).where(Match.status == "finished")
                if since:
                    q = q.where(Match.end_time >= since)  # type: ignore[operator]
                if map:
                    q = q.where(Match.map == map)
                for m in s.exec(q).all():
                    if map:
                        if m.winner_side:
                            wid = m.player1_profile_id if m.winner_side == 1 else m.player2_profile_id
                            if wid in profs:
                                score[wid] = score.get(wid, 0) + 1
                    else:
                        for n in ("1", "2"):
                            blk = (m.result or {}).get("sides", {}).get(n)
                            pid = m.player1_profile_id if n == "1" else m.player2_profile_id
                            if blk and pid in profs:
                                score[pid] = score.get(pid, 0) + int(blk.get("delta", 0))
            ranked = sorted(score.items(), key=lambda kv: (-kv[1], profs[kv[0]].display_name.lower()))
            out = []
            for i, (pid, sc) in enumerate(ranked, 1):
                p = profs[pid]
                out.append({"rank": i, "profile_id": pid, "name": p.display_name, "rating": p.rating,
                            "tier": get_tier(p.rating, ctx.cfg), "score": sc, "wins": p.wins, "losses": p.losses})
            return out

        rows = await run_db(work)
        ctx.cache[key] = (time.monotonic(), rows)
    mine = next((r for r in rows if r["profile_id"] == caller.profile_id), None)
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
