"""Database engine and the one helper every async caller uses: await run_db(fn).

run_db runs a function with a fresh sync SQLModel session in a worker thread
and commits when it returns. No session is ever held across an await.
SQLite runs in WAL mode with a 5 s busy timeout.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

import anyio
from sqlalchemy import event
from sqlalchemy.schema import CreateIndex
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import BACKEND_DIR, get_settings

log = logging.getLogger("algoarena.db")
T = TypeVar("T")

_engine = None


def _make_engine(url: str):  # type: ignore[no-untyped-def]
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True)


def get_engine():  # type: ignore[no-untyped-def]
    global _engine
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Tests and tools may point the app at another database."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url) if url else None


def session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def db_sync(fn: Callable[..., T], *args: Any) -> T:
    with session() as s:
        out = fn(s, *args)
        s.commit()
        return out


async def run_db(fn: Callable[..., T], *args: Any) -> T:
    return await anyio.to_thread.run_sync(lambda: db_sync(fn, *args))


def init_db(use_migrations: bool | None = None) -> None:
    """Bring the schema up to date.

    Uses Alembic (upgrade head) when it is installed; otherwise, and always
    under ENV=test, falls back to SQLModel.metadata.create_all.
    """
    import app.models  # noqa: F401  (register every table)

    settings = get_settings()
    if use_migrations is None:
        use_migrations = settings.env != "test"
    if use_migrations:
        try:
            from alembic import command
            from alembic.config import Config

            from sqlalchemy import inspect

            cfg = Config(str(BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
            cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
            cfg.set_main_option("skip_logging_config", "1")
            names = set(inspect(get_engine()).get_table_names())
            if "alembic_version" not in names and "profiles" in names:
                # A database made by create_all before migrations existed: adopt it.
                log.info("existing schema without alembic_version; stamping head")
                command.stamp(cfg, "head")
            command.upgrade(cfg, "head")
            return
        except ImportError:
            log.warning("alembic is not installed; creating tables directly")
    SQLModel.metadata.create_all(get_engine())
    # create_all skips tables that already exist, indexes included: add any index
    # a newer version of the models declares (without Alembic there is no migration)
    with get_engine().begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            for index in table.indexes:
                conn.execute(CreateIndex(index, if_not_exists=True))
