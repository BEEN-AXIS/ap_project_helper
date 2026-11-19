"""Queue, matches, drafts and match actions. Every mutation is a command to the
match actor; no route accepts a rating, an HP or a result from a client."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import Caller, client_ip, current
from app.api.players import match_brief
from app.context import AppContext, ctx_dep
from app.core.db import run_db
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.engine.actor import MatchActor
from app.models import Draft, Match, MatchEvent, Profile, utcnow
from app.services.judging import run_samples

router = APIRouter(tags=["matches"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JoinBody(_Body):
    mode: Literal["ranked"] = "ranked"
    map: str = Field(default="any", max_length=16)


class RespondBody(_Body):
    proposal_id: str = Field(max_length=40)
    accept: bool


class StartBody(_Body):
    map: str = Field(default="bit", max_length=16)
    personality: str | None = Field(default=None, max_length=16)


class RunBody(_Body):
    slot: int = Field(ge=0, le=3)
    language: str = Field(default="python", max_length=16)
    code: str = Field(max_length=70000)
    input: str | None = Field(default=None, max_length=70000)


class SubmitBody(_Body):
    slot: int = Field(ge=0, le=3)
    language: str = Field(default="python", max_length=16)
    code: str = Field(max_length=70000)
    cmd_id: str = Field(min_length=4, max_length=64)
    problem: str | None = Field(default=None, max_length=64)


class ActionBody(_Body):
    cmd_id: str = Field(min_length=4, max_length=64)
    slot: int | None = Field(default=None, ge=0, le=3)
    id: str | None = Field(default=None, max_length=16)


class DraftBody(_Body):
    language: str = Field(default="python", max_length=16)
    code: str = Field(max_length=70000)
    problem: str = Field(default="", max_length=64)


async def _profile(caller: Caller) -> Profile:
    p = await run_db(lambda s: s.get(Profile, caller.profile_id))
    if p is None:
        raise AppError("not_found", "Profile not found")
    return p


def _actor_for(ctx: AppContext, match_id: str, caller: Caller) -> tuple[MatchActor, int]:
    actor = ctx.matches.get(match_id)
    if actor is None:
        raise AppError("match_not_live", "This match is not running")
    side = actor.side_of(caller.profile_id)
    if side is None:
        raise AppError("forbidden", "You are not in this match")
    return actor, side


# Queue ------------------------------------------------------------------------


@router.post("/queue/join")
async def queue_join(body: JoinBody, request: Request, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    enforce(f"queue:{caller.profile_id}", ctx.cfg.rate_limits.queue_join)
    return await ctx.matchmaker.join(await _profile(caller), body.map, client_ip(request))


@router.delete("/queue")
async def queue_leave(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    await ctx.matchmaker.leave(caller.profile_id)
    return {"state": "idle"}


@router.get("/queue")
async def queue_status(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return ctx.matchmaker.status(caller.profile_id)


@router.post("/queue/respond")
async def queue_respond(body: RespondBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await ctx.matchmaker.respond(caller.profile_id, body.proposal_id, body.accept)


# Starting bot and practice matches -------------------------------------------


async def _start_vs_cpu(kind: str, body: StartBody, caller: Caller, ctx: AppContext) -> dict:
    if kind == "bot" and not ctx.cfg.feature("bots"):
        raise AppError("forbidden", "Bot matches are switched off")
    if ctx.matches.active_match_for(caller.profile_id):
        raise AppError("conflict", "You are already in a match", {"match_id": ctx.matches.active_match_for(caller.profile_id)})
    prof = await _profile(caller)
    if prof.queue_ban_until and prof.queue_ban_until > utcnow() and kind == "bot":
        raise AppError("forbidden", "Queue ban for leaving matches early")
    try:
        mc = ctx.cfg.map_cfg(body.map)
    except KeyError:
        raise AppError("validation", "Unknown map") from None
    from app.domain.tiers import get_tier

    if get_tier(prof.rating, ctx.cfg) < mc.min_tier:
        raise AppError("forbidden", f"The {body.map} map needs tier {mc.min_tier} or higher")
    await ctx.matchmaker.leave(caller.profile_id)
    if kind == "bot":
        if body.personality and body.personality not in ctx.cfg.bots.personalities:
            raise AppError("validation", "Unknown bot personality")
        opp = await ctx.matches.bot_profile(body.personality)
        actor = await ctx.matches.create_match("bot", body.map, prof, opp, opponent_kind="bot")
    else:
        opp = await ctx.matches.bot_profile("dummy")
        actor = await ctx.matches.create_match("practice", body.map, prof, opp, opponent_kind="dummy")
    return {"match_id": actor.id}


@router.post("/matches/bot")
async def start_bot(body: StartBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _start_vs_cpu("bot", body, caller, ctx)


@router.post("/matches/practice")
async def start_practice(body: StartBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _start_vs_cpu("practice", body, caller, ctx)


# Reading matches ---------------------------------------------------------------


@router.get("/matches/live")
async def live_matches(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    """Featured live matches for spectating (declared before /matches/{id})."""
    if not ctx.cfg.feature("spectate"):
        return {"matches": [], "enabled": False}
    return {"enabled": True, "matches": [
        {"id": a.id, "mode": a.m.mode, "map": a.m.map, "players": [a.side(1).name, a.side(2).name]}
        for a in ctx.matches.live_matches() if a.m.mode == "ranked" and a.m.status == "live"]}


@router.get("/matches/{match_id}")
async def get_match(match_id: str, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    actor = ctx.matches.get(match_id)
    if actor is not None:
        side = actor.side_of(caller.profile_id)
        out: dict[str, Any] = match_brief(actor.m, caller.profile_id)
        if side is not None:
            out["snapshot"] = actor.snapshot(side)
        if actor.finished:
            out["result"] = actor.m.result
        return out
    m = await run_db(lambda s: s.get(Match, match_id))
    if m is None:
        raise AppError("not_found", "Match not found")
    out = match_brief(m, caller.profile_id)
    out["result"] = m.result if m.status in ("finished", "aborted") else None
    out["players_detail"] = [
        {"side": n, "name": getattr(m, f"player{n}_name"), "rating": getattr(m, f"player{n}_rating"),
         "tier": getattr(m, f"player{n}_tier"), "max_hp": getattr(m, f"player{n}_max_hp"), "hp": getattr(m, f"player{n}_hp"),
         "skins": getattr(m, f"player{n}_skins"), "is_bot": getattr(m, f"player{n}_is_bot")} for n in (1, 2)]
    out["stage"] = {"theme": m.stage_theme, "owner_side": m.stage_owner_side}
    return out


@router.get("/matches/{match_id}/events")
async def match_events(match_id: str, after_seq: int = Query(default=0, ge=0), limit: int = Query(default=500, le=1000),
                       caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    """Public events only (no code, hands or hint text): the replay feed."""
    if not ctx.cfg.feature("replays"):
        raise AppError("forbidden", "Replays are switched off")
    actor = ctx.matches.get(match_id)
    if actor is not None and not actor.finished:
        raise AppError("conflict", "Replays open when the match ends")

    def work(s: Session) -> dict:
        m = s.get(Match, match_id)
        if m is None:
            raise AppError("not_found", "Match not found")
        rows = s.exec(select(MatchEvent).where(MatchEvent.match_id == match_id, MatchEvent.seq > after_seq,
                                               MatchEvent.visibility == "both").order_by(MatchEvent.seq).limit(limit)).all()  # type: ignore[arg-type]
        return {"match": match_brief(m, caller.profile_id), "events": [
            {"seq": r.seq, "t_ms": r.t_ms, "type": r.type, "data": r.payload} for r in rows],
            "players": [{"side": n, "name": getattr(m, f"player{n}_name"), "rating": getattr(m, f"player{n}_rating"),
                         "tier": getattr(m, f"player{n}_tier"), "max_hp": getattr(m, f"player{n}_max_hp"),
                         "skins": getattr(m, f"player{n}_skins"), "is_bot": getattr(m, f"player{n}_is_bot")} for n in (1, 2)],
            "stage": {"theme": m.stage_theme, "owner_side": m.stage_owner_side}}

    return await run_db(work)


# Actions -----------------------------------------------------------------------------


@router.post("/matches/{match_id}/run")
async def match_run(match_id: str, body: RunBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    actor, side = _actor_for(ctx, match_id, caller)
    if actor.m.status != "live":
        raise AppError("match_not_live", "The match is not live")
    slug = actor.card_slug(side, body.slot)
    enforce(f"run:{caller.profile_id}", ctx.cfg.rate_limits.run)
    if caller.profile_id in ctx.runs_inflight:
        raise AppError("busy", "A Run is already in progress")
    ctx.runs_inflight.add(caller.profile_id)
    try:
        p = ctx.problems.get(slug)
        assert p is not None
        out = await run_samples(ctx.pool, ctx.cfg, p, body.language, body.code, body.input, practice=actor.m.mode == "practice")
        out["problem"] = slug
        return out
    finally:
        ctx.runs_inflight.discard(caller.profile_id)


@router.post("/matches/{match_id}/submit", status_code=202)
async def match_submit(match_id: str, body: SubmitBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    actor, side = _actor_for(ctx, match_id, caller)
    res = await actor.send("submit", side, {"slot": body.slot, "code": body.code, "language": body.language,
                                            "problem": body.problem}, body.cmd_id)
    sub = res.get("_sub")
    return {"submission_id": sub.id if sub is not None else None, "slot": res.get("slot")}


async def _action(kind: str, match_id: str, body: ActionBody, caller: Caller, ctx: AppContext) -> dict:
    actor, side = _actor_for(ctx, match_id, caller)
    data: dict[str, Any] = {}
    if body.slot is not None:
        data["slot"] = body.slot
    if body.id is not None:
        data["id"] = body.id
    if kind in ("hint", "reroll") and body.slot is None:
        raise AppError("validation", "slot is required")
    return await actor.send(kind, side, data, body.cmd_id)


@router.post("/matches/{match_id}/block")
async def match_block(match_id: str, body: ActionBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _action("block", match_id, body, caller, ctx)


@router.post("/matches/{match_id}/hint")
async def match_hint(match_id: str, body: ActionBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _action("hint", match_id, body, caller, ctx)


@router.post("/matches/{match_id}/reroll")
async def match_reroll(match_id: str, body: ActionBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _action("reroll", match_id, body, caller, ctx)


@router.post("/matches/{match_id}/forfeit")
async def match_forfeit(match_id: str, body: ActionBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _action("forfeit", match_id, body, caller, ctx)


@router.post("/matches/{match_id}/emote")
async def match_emote(match_id: str, body: ActionBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    return await _action("emote", match_id, body, caller, ctx)


# Drafts (owner-only, last write wins) ------------------------------------------


@router.put("/matches/{match_id}/drafts/{slot}")
async def put_draft(match_id: str, slot: int, body: DraftBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    if not 0 <= slot <= 3:
        raise AppError("validation", "slot must be 0 to 3")
    if len(body.code.encode()) > ctx.cfg.match.max_code_bytes:
        raise AppError("code_too_large", "Drafts must be under 64 KB")
    actor, _side = _actor_for(ctx, match_id, caller)
    if actor.finished:
        raise AppError("match_not_live", "The match is over")

    def work(s: Session) -> dict:
        d = s.exec(select(Draft).where(Draft.match_id == match_id, Draft.profile_id == caller.profile_id,
                                       Draft.slot == slot, Draft.language == body.language)).first()
        if d is None:
            d = Draft(match_id=match_id, profile_id=caller.profile_id, slot=slot, language=body.language, code=body.code,
                      problem_slug=body.problem)
        d.code = body.code
        d.problem_slug = body.problem
        d.updated_at = utcnow()
        s.add(d)
        return {"saved_at": d.updated_at.isoformat() + "Z"}

    return await run_db(work)


@router.get("/matches/{match_id}/drafts")
async def get_drafts(match_id: str, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    def work(s: Session) -> dict:
        rows = s.exec(select(Draft).where(Draft.match_id == match_id, Draft.profile_id == caller.profile_id)).all()
        return {"drafts": [{"slot": d.slot, "language": d.language, "code": d.code, "problem": d.problem_slug,
                            "saved_at": d.updated_at.isoformat() + "Z"} for d in rows]}

    return await run_db(work)


@router.get("/matches/{match_id}/drafts/{slot}")
async def get_draft(match_id: str, slot: int, response: Response, caller: Caller = Depends(current)) -> dict:
    def work(s: Session) -> dict:
        d = s.exec(select(Draft).where(Draft.match_id == match_id, Draft.profile_id == caller.profile_id, Draft.slot == slot)).first()
        if d is None:
            raise AppError("not_found", "No draft")
        return {"slot": d.slot, "language": d.language, "code": d.code, "problem": d.problem_slug}

    return await run_db(work)
