"""Auth dependencies: the acting user always comes from the access token."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from app.context import AppContext, ctx_dep
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.core.security import decode_access_token


@dataclass(frozen=True)
class Caller:
    user_id: int
    profile_id: int
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def current(request: Request, ctx: AppContext = Depends(ctx_dep)) -> Caller:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    claims = decode_access_token(token) if token else None
    if claims is None:
        raise AppError("unauthorized", "Sign in first")
    enforce(f"rest:{claims.user_id}", ctx.cfg.rate_limits.rest)
    return Caller(claims.user_id, claims.profile_id, claims.role)


def admin(caller: Caller = Depends(current)) -> Caller:
    if not caller.is_admin:
        raise AppError("forbidden", "Admins only")
    return caller
