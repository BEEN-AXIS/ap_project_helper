"""Admin console endpoints (admin role only). Every action is written to audit_log."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import Caller, admin
from app.api.players import match_brief
from app.context import AppContext, ctx_dep
from app.core.db import run_db
from app.core.errors import AppError
from app.domain.damage import compute_preview, damage_class
from app.models import AuditLog, Flag, Inventory, Match, MatchEvent, Profile, RatingHistory, User, utcnow

router = APIRouter(prefix="/admin", tags=["admin"])


def _audit(s: Session, caller: Caller, action: str, target: str, details: dict[str, Any] | None = None) -> None:
    s.add(AuditLog(actor_id=caller.user_id, action=action, target=target, details=details or {}))


@router.get("/calculator")
async def calculator(attacker_tier: int = Query(ge=1, le=5), problem_tier: int = Query(ge=1, le=5),
                     base_damage: int | None = Query(default=None, ge=0), base_recoil: int | None = Query(default=None, ge=0),
                     caller: Caller = Depends(admin), ctx: AppContext = Depends(ctx_dep)) -> dict:
    row = ctx.cfg.tier_row(problem_tier)
    bd = row.base_damage if base_damage is None else base_damage
    br = row.base_recoil if base_recoil is None else base_recoil
    pv = compute_preview(attacker_tier, problem_tier, bd, br, ctx.cfg)
    own = ctx.cfg.tier_row(attacker_tier).max_hp
    return {"damage": pv.damage, "recoil": pv.recoil, "tier_diff": pv.tier_diff, "scenario": pv.scenario, "crit": pv.crit,
            "hits_to_kill_same_tier": -(-own // pv.damage) if pv.damage else None,
            "recoil_share_pct": round(pv.recoil * 100 / own, 1),
            "damage_class_vs_same_tier": damage_class(pv.damage, own, ctx.cfg)}


@router.get("/matches")
async def admin_matches(q: str | None = Query(default=None, max_length=40), caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> list[dict]:
        stmt = select(Match).order_by(Match.created_at.desc()).limit(100)  # type: ignore[attr-defined]
        rows = s.exec(stmt).all()
        if q:
            rows = [m for m in rows if q.lower() in (m.player1_name + m.player2_name + m.id).lower()]
        return [match_brief(m) for m in rows]

    return {"matches": await run_db(work)}


@router.get("/matches/{match_id}/events")
async def admin_events(match_id: str, caller: Caller = Depends(admin)) -> dict:
    """The full event log, private events included."""
    def work(s: Session) -> list[dict]:
        rows = s.exec(select(MatchEvent).where(MatchEvent.match_id == match_id).order_by(MatchEvent.seq)).all()  # type: ignore[arg-type]
        return [{"seq": r.seq, "t_ms": r.t_ms, "type": r.type, "visibility": r.visibility, "data": r.payload} for r in rows]

    return {"events": await run_db(work)}


class VoidBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(max_length=200)


@router.post("/matches/{match_id}/void")
async def void_match(match_id: str, body: VoidBody, caller: Caller = Depends(admin)) -> dict:
    """Reverse the match's rating_history rows and log the action."""
    def work(s: Session) -> dict:
        rows = s.exec(select(RatingHistory).where(RatingHistory.match_id == match_id, RatingHistory.voided == False)).all()  # noqa: E712
        for r in rows:
            p = s.get(Profile, r.profile_id)
            if p:
                p.rating = max(0, p.rating - r.delta)
                s.add(p)
            r.voided = True
            s.add(r)
        _audit(s, caller, "void_match", match_id, {"reason": body.reason, "rows": len(rows)})
        return {"reversed": len(rows)}

    return await run_db(work)


@router.post("/matches/{match_id}/abort")
async def abort_match(match_id: str, caller: Caller = Depends(admin), ctx: AppContext = Depends(ctx_dep)) -> dict:
    actor = ctx.matches.get(match_id)
    if actor is None:
        raise AppError("not_found", "Match is not running")
    await actor.send("abort", 0, {"reason": "admin"})
    await run_db(lambda s: _audit(s, caller, "abort_match", match_id))
    return {"ok": True}


@router.get("/flags")
async def flags(caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> list[dict]:
        return [f.model_dump(mode="json") for f in s.exec(select(Flag).order_by(Flag.created_at.desc()).limit(200)).all()]  # type: ignore[attr-defined]

    return {"flags": await run_db(work)}


class FlagAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(dismissed|warned|actioned)$")


@router.post("/flags/{flag_id}")
async def flag_action(flag_id: int, body: FlagAction, caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> dict:
        f = s.get(Flag, flag_id)
        if f is None:
            raise AppError("not_found", "No such flag")
        f.status = body.status
        s.add(f)
        _audit(s, caller, "flag_" + body.status, str(flag_id))
        return {"ok": True}

    return await run_db(work)


class SuspendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: int = Field(ge=0, le=60 * 24 * 365)


@router.post("/users/{username}/suspend")
async def suspend(username: str, body: SuspendBody, caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> dict:
        u = s.exec(select(User).where(User.username_lower == username.lower())).first()
        if u is None:
            raise AppError("not_found", "No such user")
        u.suspended_until = utcnow() + timedelta(minutes=body.minutes) if body.minutes else None
        s.add(u)
        _audit(s, caller, "suspend", username, {"minutes": body.minutes})
        return {"suspended_until": u.suspended_until.isoformat() if u.suspended_until else None}

    return await run_db(work)


class GrantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skin_id: str = Field(max_length=48)


@router.post("/users/{username}/grant-skin")
async def grant_skin(username: str, body: GrantBody, caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> dict:
        u = s.exec(select(User).where(User.username_lower == username.lower())).first()
        p = s.exec(select(Profile).where(Profile.user_id == u.id)).first() if u else None
        if p is None:
            raise AppError("not_found", "No such user")
        if not s.exec(select(Inventory).where(Inventory.profile_id == p.id, Inventory.skin_id == body.skin_id)).first():
            s.add(Inventory(profile_id=p.id or 0, skin_id=body.skin_id, source="admin"))
        _audit(s, caller, "grant_skin", username, {"skin_id": body.skin_id})
        return {"ok": True}

    return await run_db(work)


@router.post("/users/{username}/reset-daily-cap")
async def reset_cap(username: str, caller: Caller = Depends(admin)) -> dict:
    def work(s: Session) -> dict:
        u = s.exec(select(User).where(User.username_lower == username.lower())).first()
        p = s.exec(select(Profile).where(Profile.user_id == u.id)).first() if u else None
        if p is None:
            raise AppError("not_found", "No such user")
        p.bot_gain_today = 0
        p.casual_ap_today = 0
        s.add(p)
        _audit(s, caller, "reset_daily_cap", username)
        return {"ok": True}

    return await run_db(work)


@router.post("/problems/reload")
async def reload_problems(caller: Caller = Depends(admin), ctx: AppContext = Depends(ctx_dep)) -> dict:
    await ctx.problems.reload()
    return {"problems": len(ctx.problems.by_slug)}
