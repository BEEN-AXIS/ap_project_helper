"""Sign-up, login, refresh-token rotation, logout and WebSocket tickets."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import Caller, client_ip, current
from app.context import AppContext, ctx_dep
from app.core.db import run_db
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.core.security import (
    REFRESH_COOKIE, REFRESH_TTL_S, USERNAME_RE, hash_password, hash_token, make_access_token, new_refresh_token,
    password_problem, tickets, verify_password,
)
from app.models import Profile, RefreshToken, User, utcnow
from app.services.profiles import profile_private

router = APIRouter(prefix="/auth", tags=["auth"])
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class SignupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)
    avatar_color: str | None = Field(default=None, max_length=9)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class TicketBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["lobby", "match", "spectate"]
    match_id: str | None = Field(default=None, max_length=36)


def _issue_refresh(s: Session, user_id: int) -> str:
    raw, digest = new_refresh_token()
    s.add(RefreshToken(user_id=user_id, token_hash=digest, expires_at=utcnow() + timedelta(seconds=REFRESH_TTL_S)))
    return raw


def _set_cookie(resp: Response, raw: str, ctx: AppContext) -> None:
    resp.set_cookie(REFRESH_COOKIE, raw, max_age=REFRESH_TTL_S, httponly=True, secure=ctx.settings.secure_cookies,
                    samesite="lax", path="/api/auth")


def _session_payload(s: Session, u: User, p: Profile, ctx: AppContext) -> dict:
    return {"access_token": make_access_token(u.id or 0, p.id or 0, u.role), "token_type": "bearer",
            "profile": profile_private(s, p, ctx.cfg)}


@router.post("/signup")
async def signup(body: SignupBody, request: Request, response: Response, ctx: AppContext = Depends(ctx_dep)) -> dict:
    enforce(f"signup:{client_ip(request)}", ctx.cfg.rate_limits.signup)
    name = body.username.strip()
    if not USERNAME_RE.match(name):
        raise AppError("validation", "Username must be 3 to 20 letters, digits or underscores", {"field": "username"})
    problem = password_problem(body.password, name)
    if problem:
        raise AppError("validation", problem, {"field": "password"})
    color = body.avatar_color if body.avatar_color and COLOR_RE.match(body.avatar_color) else "#3b82f6"
    pw_hash = hash_password(body.password)

    def work(s: Session) -> tuple[dict, str]:
        if s.exec(select(User).where(User.username_lower == name.lower())).first():
            raise AppError("conflict", "That username is taken", {"field": "username"})
        u = User(username=name, username_lower=name.lower(), password_hash=pw_hash)
        s.add(u)
        s.flush()
        p = Profile(user_id=u.id, display_name=name, rating=ctx.cfg.rating.starting, peak_rating=ctx.cfg.rating.starting,
                    avatar_color=color)
        s.add(p)
        s.flush()
        from app.seed import grant_defaults

        grant_defaults(s, p)
        s.flush()
        return _session_payload(s, u, p, ctx), _issue_refresh(s, u.id or 0)

    payload, raw = await run_db(work)
    _set_cookie(response, raw, ctx)
    return payload


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, ctx: AppContext = Depends(ctx_dep)) -> dict:
    uname = body.username.strip().lower()
    enforce(f"login-ip:{client_ip(request)}", ctx.cfg.rate_limits.login)
    enforce(f"login-user:{uname}", ctx.cfg.rate_limits.login)

    def find(s: Session) -> User | None:
        return s.exec(select(User).where(User.username_lower == uname)).first()

    u = await run_db(find)
    if u is None or not verify_password(body.password, u.password_hash):
        raise AppError("unauthorized", "Wrong username or password")
    if u.suspended_until and u.suspended_until > utcnow():
        raise AppError("forbidden", "This account is suspended", {"until": u.suspended_until.isoformat()})

    def work(s: Session) -> tuple[dict, str]:
        p = s.exec(select(Profile).where(Profile.user_id == u.id)).one()
        return _session_payload(s, u, p, ctx), _issue_refresh(s, u.id or 0)

    payload, raw = await run_db(work)
    _set_cookie(response, raw, ctx)
    return payload


@router.post("/refresh")
async def refresh(request: Request, response: Response, ctx: AppContext = Depends(ctx_dep)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AppError("unauthorized", "No session")
    digest = hash_token(raw)

    def work(s: Session) -> tuple[dict, str]:
        row = s.exec(select(RefreshToken).where(RefreshToken.token_hash == digest)).first()
        if row is None or row.expires_at < utcnow():
            raise AppError("unauthorized", "Session expired")
        if row.revoked_at is not None:
            # A rotated token was replayed: revoke every session of this user.
            for t in s.exec(select(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at == None)).all():  # noqa: E711
                t.revoked_at = utcnow()
                s.add(t)
            s.commit()
            raise AppError("unauthorized", "Session expired")
        row.revoked_at = utcnow()
        s.add(row)
        u = s.get(User, row.user_id)
        assert u is not None
        if u.suspended_until and u.suspended_until > utcnow():
            raise AppError("forbidden", "This account is suspended")
        p = s.exec(select(Profile).where(Profile.user_id == u.id)).one()
        return _session_payload(s, u, p, ctx), _issue_refresh(s, u.id or 0)

    payload, new_raw = await run_db(work)
    _set_cookie(response, new_raw, ctx)
    return payload


@router.post("/logout")
async def logout(request: Request, response: Response, ctx: AppContext = Depends(ctx_dep)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        digest = hash_token(raw)

        def work(s: Session) -> None:
            row = s.exec(select(RefreshToken).where(RefreshToken.token_hash == digest)).first()
            if row and row.revoked_at is None:
                row.revoked_at = utcnow()
                s.add(row)

        await run_db(work)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


@router.post("/ws-ticket")
async def ws_ticket(body: TicketBody, caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    if body.scope == "match":
        if not body.match_id:
            raise AppError("validation", "match_id is required")
        actor = ctx.matches.get(body.match_id)
        if actor is None:
            raise AppError("not_found", "Match not found or already archived")
        if actor.side_of(caller.profile_id) is None:
            raise AppError("forbidden", "You are not in this match")
    if body.scope == "spectate":
        raise AppError("forbidden", "Spectating is switched off in this build")
    return {"ticket": tickets.issue(caller.user_id, caller.profile_id, body.scope, body.match_id), "expires_in": 30}
