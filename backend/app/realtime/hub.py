"""In-process WebSocket hub. Behind a small interface so a Redis-backed hub can
replace it when the server scales past one process."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, Protocol

log = logging.getLogger("algoarena.hub")


class Conn(Protocol):
    async def send_json(self, data: Any) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


def envelope(type_: str, data: dict[str, Any], seq: int | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"v": 1, "type": type_, "t": int(time.time() * 1000), "data": data}
    if seq is not None:
        msg["seq"] = seq
    return msg


class Connection:
    """Wraps a socket so sends never interleave and a dead peer never raises."""

    def __init__(self, ws: Any, profile_id: int) -> None:
        self.ws = ws
        self.profile_id = profile_id
        self.lock = asyncio.Lock()
        self.closed = False

    async def send(self, msg: dict[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            async with self.lock:
                await self.ws.send_text(json.dumps(msg, separators=(",", ":")))
            return True
        except Exception:
            self.closed = True
            return False

    async def close(self, code: int = 1000) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(Exception):
            await self.ws.close(code=code)


class Hub:
    def __init__(self) -> None:
        self.match_conns: dict[str, dict[int, Connection]] = {}
        self.lobby: dict[int, Connection] = {}

    # Match rooms ---------------------------------------------------------------
    def attach(self, match_id: str, side: int, conn: Connection) -> Connection | None:
        room = self.match_conns.setdefault(match_id, {})
        old = room.get(side)
        room[side] = conn
        return old if old is not conn else None

    def detach(self, match_id: str, side: int, conn: Connection) -> bool:
        room = self.match_conns.get(match_id, {})
        if room.get(side) is conn:
            del room[side]
            return True
        return False

    def current(self, match_id: str, side: int) -> Connection | None:
        return self.match_conns.get(match_id, {}).get(side)

    async def send_side(self, match_id: str, side: int, msg: dict[str, Any]) -> None:
        c = self.current(match_id, side)
        if c is not None:
            await c.send(msg)

    async def broadcast(self, match_id: str, visibility: str, msg: dict[str, Any]) -> None:
        room = self.match_conns.get(match_id, {})
        for side, c in list(room.items()):
            if visibility == "both" or visibility == f"p{side}":
                await c.send(msg)

    def drop_room(self, match_id: str) -> None:
        self.match_conns.pop(match_id, None)

    # Lobby -------------------------------------------------------------------------
    def lobby_attach(self, profile_id: int, conn: Connection) -> Connection | None:
        old = self.lobby.get(profile_id)
        self.lobby[profile_id] = conn
        return old if old is not conn else None

    def lobby_detach(self, profile_id: int, conn: Connection) -> bool:
        if self.lobby.get(profile_id) is conn:
            del self.lobby[profile_id]
            return True
        return False

    async def lobby_send(self, profile_id: int, type_: str, data: dict[str, Any]) -> None:
        c = self.lobby.get(profile_id)
        if c is not None:
            await c.send(envelope(type_, data))

    async def lobby_broadcast(self, type_: str, data: dict[str, Any]) -> None:
        for c in list(self.lobby.values()):
            await c.send(envelope(type_, data))
