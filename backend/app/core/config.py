"""Environment settings and the shared game config loader."""

from __future__ import annotations

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.domain.gameconfig import GameConfig

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
SHARED_DIR = Path(os.environ.get("SHARED_DIR", REPO_ROOT / "shared"))

DEFAULT_JWT_SECRET = "dev-only-change-me-dev-only-change-me-dev-only"


def _load_dotenv() -> None:
    """Minimal .env reader (KEY=VALUE lines); real env vars always win."""
    for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Settings(BaseModel):
    env: str = "dev"  # dev | test | prod
    database_url: str = f"sqlite:///{BACKEND_DIR / 'algoarena.db'}"
    jwt_secret: str = DEFAULT_JWT_SECRET
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    judge_backend: str = "auto"  # auto | docker | subprocess | judge0 | fake
    judge_concurrency: int = 4
    judge0_url: str = ""
    judge_image: str = "algoarena-judge:latest"
    match_max_minutes: int | None = None
    bot_fallback_seconds: int | None = None
    bot_time_scale: float | None = None
    log_level: str = "INFO"
    frontend_dist: str = str(REPO_ROOT / "frontend" / "dist")
    secure_cookies: bool = False

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


def _env_int(name: str) -> int | None:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else None


def _env_float(name: str) -> float | None:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else None


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    env = os.environ.get("ENV", "dev")
    secret = os.environ.get("JWT_SECRET", DEFAULT_JWT_SECRET)
    if env == "prod" and secret in ("", DEFAULT_JWT_SECRET):
        raise RuntimeError("Refusing to boot in prod with the default JWT_SECRET")
    if env == "test" and secret == DEFAULT_JWT_SECRET:
        secret = "test-secret-" + secrets.token_hex(24)
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    s = Settings(
        env=env,
        jwt_secret=secret,
        judge_backend=os.environ.get("JUDGE_BACKEND", "auto"),
        judge_concurrency=_env_int("JUDGE_CONCURRENCY") or 4,
        judge0_url=os.environ.get("JUDGE0_URL", ""),
        judge_image=os.environ.get("JUDGE_IMAGE", "algoarena-judge:latest"),
        match_max_minutes=_env_int("MATCH_MAX_MINUTES"),
        bot_fallback_seconds=_env_int("BOT_FALLBACK_SECONDS"),
        bot_time_scale=_env_float("BOT_TIME_SCALE"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        secure_cookies=env == "prod",
    )
    if os.environ.get("DATABASE_URL"):
        s.database_url = os.environ["DATABASE_URL"]
    if origins:
        s.cors_origins = origins
    if os.environ.get("FRONTEND_DIST"):
        s.frontend_dist = os.environ["FRONTEND_DIST"]
    return s


def load_game_config_file(path: Path | None = None) -> GameConfig:
    p = path or (SHARED_DIR / "game-config.json")
    return GameConfig.model_validate(json.loads(p.read_text()))


@lru_cache
def get_game_config() -> GameConfig:
    """The validated game config with the few env overrides applied."""
    cfg = load_game_config_file()
    s = get_settings()
    patch: dict[str, object] = {}
    if s.bot_time_scale is not None:
        patch["bot_time_scale"] = s.bot_time_scale
    if s.match_max_minutes is not None:
        patch["match"] = cfg.match.model_copy(update={"max_minutes": s.match_max_minutes})
    if s.bot_fallback_seconds is not None:
        patch["matchmaking"] = cfg.matchmaking.model_copy(
            update={"bot_fallback_s": s.bot_fallback_seconds}
        )
    if s.judge_concurrency:
        patch["judge"] = cfg.judge.model_copy(update={"concurrency": s.judge_concurrency})
    return cfg.model_copy(update=patch) if patch else cfg


def public_config(cfg: GameConfig) -> dict[str, object]:
    """The part of the config the client may see (GET /api/config)."""
    data = cfg.model_dump()
    data.pop("bots", None)
    data.pop("rate_limits", None)
    judge = data.pop("judge")
    data["judge"] = {
        "stop_on_first_fail": judge["stop_on_first_fail"],
        "source_limit_kb": judge["source_limit_kb"],
        "custom_input_limit_kb": judge["custom_input_limit_kb"],
        "run_time_cap_ms": judge["run_time_cap_ms"],
    }
    return data
