"""Render alembic/versions/0001_initial.py from the SQLModel metadata.

Historical: 0001 is the schema as first shipped. Later changes are new
revisions (0002_equipped_weapon, ...), so do not re-render 0001 now.

Alembic's own autogenerate does the same job once alembic is installed
(`alembic revision --autogenerate -m "..."`); this script exists so the
baseline migration is reproducible without a database.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: E402,F401


def render_type(t: sa.types.TypeEngine) -> str:
    name = type(t).__name__
    if name == "AutoString":
        return f"sqlmodel.sql.sqltypes.AutoString(length={t.length})" if t.length else "sqlmodel.sql.sqltypes.AutoString()"
    if isinstance(t, sa.DateTime):
        return "sa.DateTime(timezone=True)" if t.timezone else "sa.DateTime()"
    if isinstance(t, (sa.Integer, sa.Boolean, sa.Text, sa.JSON, sa.Float)):
        return f"sa.{name}()"
    raise SystemExit(f"unhandled column type {name}")


def render_table(t: sa.Table) -> list[str]:
    out = [f"    op.create_table(", f"        {t.name!r},"]
    for c in t.columns:
        args = [repr(c.name), render_type(c.type)]
        for fk in c.foreign_keys:
            args.append(f"sa.ForeignKey({fk.target_fullname!r})")
        if c.primary_key:
            args.append("primary_key=True")
        args.append(f"nullable={c.nullable}")
        out.append(f"        sa.Column({', '.join(args)}),")
    for con in sorted(t.constraints, key=lambda x: x.name or ""):
        if isinstance(con, sa.UniqueConstraint):
            cols = ", ".join(repr(c.name) for c in con.columns)
            nm = f", name={con.name!r}" if con.name else ""
            out.append(f"        sa.UniqueConstraint({cols}{nm}),")
    out.append("    )")
    for ix in sorted(t.indexes, key=lambda i: i.name or ""):
        cols = ", ".join(repr(c.name) for c in ix.columns)
        out.append(f"    op.create_index({ix.name!r}, {t.name!r}, [{cols}], unique={bool(ix.unique)})")
    return out


def main() -> None:
    tables = SQLModel.metadata.sorted_tables
    up: list[str] = []
    for t in tables:
        up += render_table(t)
        up.append("")
    down = []
    for t in reversed(tables):
        for ix in sorted(t.indexes, key=lambda i: i.name or ""):
            down.append(f"    op.drop_index({ix.name!r}, table_name={t.name!r})")
        down.append(f"    op.drop_table({t.name!r})")
    body = f'''"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-19

Rendered by scripts/render_initial_migration.py from app.models.
"""
from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
{chr(10).join(up).rstrip()}


def downgrade() -> None:
{chr(10).join(down)}
'''
    dest = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_initial.py"
    dest.write_text(body)
    print(f"wrote {dest} ({len(tables)} tables)")


if __name__ == "__main__":
    main()
