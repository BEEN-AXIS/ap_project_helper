"""The baseline migration builds exactly the schema the models declare.

Alembic is optional at runtime, so this drives upgrade() with a small
stand-in for `alembic.op` and compares the result with create_all.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa
from sqlmodel import SQLModel

import app.models  # noqa: F401

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_initial.py"


def _schema(engine: sa.Engine) -> dict:
    insp = sa.inspect(engine)
    out = {}
    for t in sorted(insp.get_table_names()):
        cols = {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns(t)}
        idx = sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(t))
        uq = sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(t))
        pk = tuple(insp.get_pk_constraint(t)["constrained_columns"])
        out[t] = (cols, idx, uq, pk)
    return out


def test_initial_migration_matches_models(tmp_path: Path) -> None:
    ref = sa.create_engine(f"sqlite:///{tmp_path / 'ref.db'}")
    SQLModel.metadata.create_all(ref)

    mig = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    md = sa.MetaData()
    conn = mig.connect()

    def create_table(name, *cols):
        tbl = sa.Table(name, md, *cols)
        tbl.create(conn)
        return tbl

    def create_index(name, table, columns, unique=False):
        tbl = md.tables[table]
        sa.Index(name, *[tbl.c[c] for c in columns], unique=unique).create(conn)

    fake_op = types.SimpleNamespace(create_table=create_table, create_index=create_index)
    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = fake_op  # type: ignore[attr-defined]
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = alembic_mod
    try:
        spec = importlib.util.spec_from_file_location("mig_0001", MIGRATION)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(mod)
        mod.upgrade()
        conn.commit()
    finally:
        conn.close()
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            del sys.modules["alembic"]
    assert _schema(mig) == _schema(ref)
