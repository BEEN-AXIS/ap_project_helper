"""WebSocket endpoints: /ws/lobby and /ws/match/{id}, authenticated with a
single-use ticket. The battle socket is mostly server push; commands go over
REST. Messages: {"v": 1, "type", "seq"?, "t", "data"}."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.context import get_ctx
from app.core.ratelimit import MemoryRateLimiter
from app.core.security import tickets
from app.realtime.hub import Connection, envelope

router = APIRouter()
log = logging.getLogger("algoarena.ws")
_ws_limiter = MemoryRateLimiter()


async def _recv_json(ws: WebSocket, timeout: float | None = None) -> dict | None:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout) if timeout else await ws.receive_text()
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (TimeoutError, json.JSONDecodeError):
        return None


@router.websocket("/ws/lobby")
async def ws_lobby(ws: WebSocket) -> None:
    ctx = get_ctx(ws)
    t = tickets.consume(ws.query_params.get("ticket", ""), "lobby")
    if t is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = Connection(ws, t.profile_id)
    old = ctx.hub.lobby_attach(t.profile_id, conn)
    if old is not None:
        await old.send(envelope("session.moved", {"reason": "session_moved"}))
        await old.close(4001)
    ctx.matchmaker.lobby_opened(t.profile_id)
    await conn.send(envelope("hello", {"queue": ctx.matchmaker.status(t.profile_id)}))
    await ctx.hub.lobby_broadcast("online.count", {"count": len(ctx.hub.lobby)})
    try:
        while True:
            msg = await _recv_json(ws)
            if msg is None:
                continue
            ok, _ = _ws_limiter.hit(f"lobby:{id(conn)}", ctx.cfg.rate_limits.ws_msgs)
            if not ok:
                continue
            if msg.get("type") == "ping":
                await conn.send(envelope("pong", {"id": (msg.get("data") or {}).get("id")}))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # pragma: no cover
        log.debug("lobby socket error: %s", e)
    finally:
        if ctx.hub.lobby_detach(t.profile_id, conn):
            ctx.matchmaker.lobby_closed(t.profile_id)
        with contextlib.suppress(Exception):
            await ctx.hub.lobby_broadcast("online.count", {"count": len(ctx.hub.lobby)})


@router.websocket("/ws/match/{match_id}")
async def ws_match(ws: WebSocket, match_id: str) -> None:
    ctx = get_ctx(ws)
    t = tickets.consume(ws.query_params.get("ticket", ""), "match", match_id)
    actor = ctx.matches.get(match_id)
    if t is None or actor is None:
        await ws.close(code=4401 if t is None else 4404)
        return
    side = actor.side_of(t.profile_id)
    if side is None:
        await ws.close(code=4403)
        return
    await ws.accept()
    conn = Connection(ws, t.profile_id)
    hello = await _recv_json(ws, timeout=10)
    if not hello or hello.get("type") != "hello":
        await conn.send(envelope("error", {"code": "validation", "message": "send hello first"}))
        await conn.close(4400)
        return
    last_seq = int((hello.get("data") or {}).get("last_seq") or 0)
    try:
        await actor.send("join", side, {"conn": conn, "last_seq": last_seq})
    except Exception:
        await conn.close(4500)
        return
    try:
        while True:
            msg = await _recv_json(ws)
            if msg is None:
                continue
            ok, _ = _ws_limiter.hit(f"match:{id(conn)}", ctx.cfg.rate_limits.ws_msgs)
            if not ok:
                continue
            typ = msg.get("type")
            data = msg.get("data") or {}
            if typ == "ping":
                await conn.send(envelope("pong", {"id": data.get("id"), "server_time_ms": ctx.clock.wall_ms()}))
            elif typ == "activity":
                actor.enqueue_cmd("activity", side, {"state": data.get("state")})
            elif typ == "emote":
                with contextlib.suppress(Exception):
                    await actor.send("emote", side, {"id": data.get("id")}, str(data.get("cmd_id") or "") or None)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # pragma: no cover
        log.debug("match socket error: %s", e)
    finally:
        conn.closed = True
        actor.enqueue_cmd("leave", side, {"conn": conn})
