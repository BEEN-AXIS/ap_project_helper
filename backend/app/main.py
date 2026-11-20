"""AlgoArena API: FastAPI app factory and start-up wiring.

    uvicorn app.main:app --reload       (from backend/)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import admin, auth, matches, players
from app.context import AppContext, ctx_dep
from app.core.clock import Clock, RealClock
from app.core.config import get_game_config, get_settings, public_config
from app.core.db import db_sync, init_db
from app.core.errors import envelope, install_error_handlers
from app.core.logging import RequestIdMiddleware, setup_logging
from app.engine.matchmaker import Matchmaker
from app.engine.service import MatchService
from app.judge import language_tools_present, make_runner
from app.judge.pool import JudgePool
from app.realtime import ws
from app.realtime.hub import Hub
from app.services.problems import ProblemCache

log = logging.getLogger("algoarena")
MAX_BODY = 256 * 1024


class BodyLimitMiddleware:
    """Reject JSON bodies over 256 KB before they are read."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length and int(length) > MAX_BODY:
                resp = JSONResponse(envelope("validation", "Request body too large"), status_code=413)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
           "img-src 'self' data: blob:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                h = message.setdefault("headers", [])
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                      (b"referrer-policy", b"strict-origin-when-cross-origin"), (b"content-security-policy", self.CSP.encode())]
            await send(message)

        await self.app(scope, receive, _send)


def build_context(clock: Clock | None = None) -> AppContext:
    settings = get_settings()
    cfg = get_game_config()
    runner = make_runner(settings)
    pool = JudgePool(runner, cfg.judge.concurrency, cfg.judge.max_queued, cfg.judge.queue_timeout_s, cfg.judge.job_timeout_s)
    hub = Hub()
    problems = ProblemCache()
    clk = clock or RealClock()
    svc = MatchService(cfg, clk, hub, pool, problems)
    mm = Matchmaker(cfg, hub, svc)
    return AppContext(settings, cfg, clk, runner, pool, hub, problems, svc, mm)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    aborted = db_sync(MatchService.abort_stale_sync)
    if aborted:
        log.warning("aborted %d matches left running by a previous server", aborted)
    ctx: AppContext = app.state.ctx if getattr(app.state, "ctx", None) else build_context()
    app.state.ctx = ctx
    await ctx.problems.reload()
    await ctx.pool.start()
    ctx.matchmaker.start()
    if not ctx.runner.sandboxed:
        log.warning("judge backend %s is NOT a sandbox (DEV SANDBOX)", ctx.runner.name)
    log.info("started", extra={"fields": {"env": settings.env, "judge": ctx.runner.name, "problems": len(ctx.problems.by_slug)}})
    try:
        yield
    finally:
        await ctx.matchmaker.stop()
        await ctx.matches.shutdown()
        await ctx.pool.stop()


meta = APIRouter(tags=["meta"])


@meta.get("/config")
async def config(ctx: AppContext = Depends(ctx_dep)) -> dict:
    data = public_config(ctx.cfg)
    try:
        from app.skins.registry import registry_version

        data["skin_registry_version"] = registry_version()
    except ImportError:
        data["skin_registry_version"] = None
    data["judge_backend"] = {"name": ctx.runner.name, "sandboxed": ctx.runner.sandboxed}
    present = language_tools_present(ctx.cfg, ctx.runner.name)
    for lang in data["languages"]:
        lang["available"] = present.get(lang["id"], False)
    return data


@meta.get("/healthz")
async def healthz(ctx: AppContext = Depends(ctx_dep)) -> dict:
    from sqlalchemy import text

    from app.core.db import get_engine

    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    judge = await ctx.runner.healthcheck()
    return {"ok": db_ok and judge.ok, "database": db_ok,
            "judge": {"backend": judge.name, "ok": judge.ok, "sandboxed": judge.sandboxed, "detail": judge.detail},
            "problems": len(ctx.problems.by_slug)}


@meta.get("/metrics")
async def metrics(ctx: AppContext = Depends(ctx_dep)) -> dict:
    return {"queue_length": len(ctx.matchmaker.queue), "live_matches": len(ctx.matches.live_matches()),
            "lobby_sockets": len(ctx.hub.lobby), "judge": ctx.pool.metrics.snapshot(ctx.pool.queued)}


def create_app(ctx: AppContext | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AlgoArena", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    if ctx is not None:
        app.state.ctx = ctx
    install_error_handlers(app)
    api = APIRouter(prefix="/api")
    for r in (meta, auth.router, players.router, matches.router, admin.router):
        api.include_router(r)
    try:
        from app.api import skins

        api.include_router(skins.router)
    except ImportError:
        pass
    app.include_router(api)
    app.include_router(ws.router)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)

    dist = Path(settings.frontend_dist)
    if dist.is_dir() and (dist / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str, request: Request):  # type: ignore[no-untyped-def]
            if path.startswith(("api/", "ws/")):
                return JSONResponse(envelope("not_found", "Not found"), status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
