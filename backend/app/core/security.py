"""Passwords (Argon2id), JWT access tokens, refresh tokens and WebSocket tickets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass

import jwt

from app.core.config import get_settings

# Argon2id ---------------------------------------------------------------------
# OWASP's minimum profile: 19 MiB, 2 iterations, 1 lane.
ARGON_M_KIB = 19456
ARGON_T = 2
ARGON_P = 1

COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123",
    "qwertyuiop", "iloveyou", "11111111", "00000000", "abc12345", "abcd1234", "letmein1",
    "welcome1", "admin123", "monkey123", "dragon12", "sunshine", "princess", "football",
    "baseball", "superman", "trustno1", "starwars", "passw0rd", "p@ssw0rd", "algoarena",
}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _argon2id(password: str, salt: bytes, m: int, t: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

    return Argon2id(salt=salt, length=32, iterations=t, lanes=p, memory_cost=m).derive(password.encode())


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _argon2id(password, salt, ARGON_M_KIB, ARGON_T, ARGON_P)
    return f"$argon2id$v=19$m={ARGON_M_KIB},t={ARGON_T},p={ARGON_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, alg, _v, params, salt_b64, hash_b64 = encoded.split("$")
        if alg != "argon2id":
            return False
        kv = dict(item.split("=") for item in params.split(","))
        digest = _argon2id(password, _unb64(salt_b64), int(kv["m"]), int(kv["t"]), int(kv["p"]))
        return hmac.compare_digest(digest, _unb64(hash_b64))
    except Exception:
        return False


def password_problem(password: str, username: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > 128:
        return "Password is too long"
    if password.lower() in COMMON_PASSWORDS or password.lower() == username.lower():
        return "That password is too common"
    return None


# JWT access tokens ------------------------------------------------------------
ACCESS_TTL_S = 15 * 60
REFRESH_TTL_S = 7 * 24 * 3600
REFRESH_COOKIE = "aa_refresh"


def make_access_token(user_id: int, profile_id: int, role: str) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "pid": profile_id, "role": role, "iat": now, "exp": now + ACCESS_TTL_S, "typ": "access"}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    profile_id: int
    role: str


def decode_access_token(token: str) -> TokenClaims | None:
    try:
        p = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        if p.get("typ") != "access":
            return None
        return TokenClaims(int(p["sub"]), int(p["pid"]), str(p.get("role", "player")))
    except Exception:
        return None


# Refresh tokens: random, stored only as a hash, rotated on every use ----------


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# Single-use WebSocket tickets (30 s, bound to the user) ------------------------


@dataclass
class Ticket:
    user_id: int
    profile_id: int
    scope: str  # lobby | match | spectate
    match_id: str | None
    expires_at: float


class TicketStore:
    TTL_S = 30.0

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}

    def issue(self, user_id: int, profile_id: int, scope: str, match_id: str | None) -> str:
        self._sweep()
        t = secrets.token_urlsafe(24)
        self._tickets[t] = Ticket(user_id, profile_id, scope, match_id, time.monotonic() + self.TTL_S)
        return t

    def consume(self, ticket: str, scope: str, match_id: str | None = None) -> Ticket | None:
        t = self._tickets.pop(ticket, None)
        if t is None or t.expires_at < time.monotonic() or t.scope != scope:
            return None
        if scope in ("match", "spectate") and t.match_id != match_id:
            return None
        return t

    def _sweep(self) -> None:
        now = time.monotonic()
        for k in [k for k, v in self._tickets.items() if v.expires_at < now]:
            self._tickets.pop(k, None)


tickets = TicketStore()
