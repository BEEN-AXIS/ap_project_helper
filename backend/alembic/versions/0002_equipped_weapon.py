"""equipped weapon

Revision ID: 0002_equipped_weapon
Revises: 0001_initial
Create Date: 2026-11-20
"""
from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0002_equipped_weapon"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(
            sa.Column(
                "equipped_weapon",
                sqlmodel.sql.sqltypes.AutoString(length=48),
                nullable=False,
                server_default="weapon.fireball",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("equipped_weapon")
