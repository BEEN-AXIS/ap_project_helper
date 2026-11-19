"""Process-wide services, built once at start-up and reachable from handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from starlette.requests import HTTPConnection

from app.core.clock import Clock
from app.core.config import Settings
from app.domain.gameconfig import GameConfig
from app.engine.matchmaker import Matchmaker
from app.engine.service import MatchService
from app.judge.pool import JudgePool
from app.judge.runner import Runner
from app.realtime.hub import Hub
from app.services.problems import ProblemCache


@dataclass
class AppContext:
    settings: Settings
    cfg: GameConfig
    clock: Clock
    runner: Runner
    pool: JudgePool
    hub: Hub
    problems: ProblemCache
    matches: MatchService
    matchmaker: Matchmaker
    runs_inflight: set[int] = field(default_factory=set)
    cache: dict[str, tuple[float, Any]] = field(default_factory=dict)


def get_ctx(conn: HTTPConnection) -> AppContext:
    return conn.app.state.ctx  # type: ignore[no-any-return]


def ctx_dep(request: Request) -> AppContext:
    return get_ctx(request)
