"""indexes for the slow reads in dbms/05_query_timings.md

Revision ID: 0003_query_indexes
Revises: 0002_equipped_weapon
Create Date: 2026-11-23

Six indexes for reads that scanned a whole table: the all-time leaderboard and
a player's rank, the weekly and map leaderboards, the admin match list, the
profile lookup by name, and finding a bot. The WHERE clauses repeat the app's
own filters, which is how SQLite and PostgreSQL know a query can use a partial
index. Booleans are written per dialect (SQLite stores them as 0 and 1).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_query_indexes"
down_revision = "0002_equipped_weapon"
branch_labels = None
depends_on = None

PEOPLE = {"sqlite_where": sa.text("is_bot = 0 AND user_id IS NOT NULL"),
          "postgresql_where": sa.text("is_bot = false AND user_id IS NOT NULL")}
BOTS = {"sqlite_where": sa.text("is_bot = 1"), "postgresql_where": sa.text("is_bot = true")}
FINISHED = {"sqlite_where": sa.text("status = 'finished'"), "postgresql_where": sa.text("status = 'finished'")}
WON = {"sqlite_where": sa.text("status = 'finished' AND winner_side IS NOT NULL"),
       "postgresql_where": sa.text("status = 'finished' AND winner_side IS NOT NULL")}


def upgrade() -> None:
    op.create_index("ix_profiles_ladder", "profiles", [sa.text("rating DESC"), sa.text("lower(display_name)")], **PEOPLE)
    op.create_index("ix_profiles_display_name_lower", "profiles", [sa.text("lower(display_name)")])
    op.create_index("ix_profiles_bot_personality", "profiles", ["personality"], **BOTS)
    op.create_index("ix_matches_created_at", "matches", ["created_at"])
    op.create_index("ix_matches_finished_end_time", "matches", ["end_time"], **FINISHED)
    op.create_index("ix_matches_map_winners", "matches", ["map"],
                    postgresql_include=["winner_side", "player1_profile_id", "player2_profile_id"], **WON)


def downgrade() -> None:
    for name, table in (("ix_matches_map_winners", "matches"), ("ix_matches_finished_end_time", "matches"),
                        ("ix_matches_created_at", "matches"), ("ix_profiles_bot_personality", "profiles"),
                        ("ix_profiles_display_name_lower", "profiles"), ("ix_profiles_ladder", "profiles")):
        op.drop_index(name, table_name=table)
