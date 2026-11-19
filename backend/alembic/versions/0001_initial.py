"""initial schema

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
    op.create_table(
        'achievements',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('earned_at', sa.DateTime(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('profile_id', 'key'),
    )
    op.create_index('ix_achievements_profile_id', 'achievements', ['profile_id'], unique=False)

    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('target', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    op.create_table(
        'drafts',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('language', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('code', sa.Text(), nullable=True),
        sa.Column('problem_slug', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('match_id', 'profile_id', 'slot', 'language'),
    )
    op.create_index('ix_drafts_match_id', 'drafts', ['match_id'], unique=False)
    op.create_index('ix_drafts_profile_id', 'drafts', ['profile_id'], unique=False)

    op.create_table(
        'flags',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=True),
        sa.Column('profile_id', sa.Integer(), nullable=True),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('severity', sa.Integer(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_flags_match_id', 'flags', ['match_id'], unique=False)
    op.create_index('ix_flags_profile_id', 'flags', ['profile_id'], unique=False)

    op.create_table(
        'matches',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=36), primary_key=True, nullable=False),
        sa.Column('mode', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('map', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('stage_theme', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('stage_owner_side', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('elapsed_ms', sa.Integer(), nullable=False),
        sa.Column('end_reason', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column('outcome', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column('winner_side', sa.Integer(), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('decks', sa.JSON(), nullable=True),
        sa.Column('last_seq', sa.Integer(), nullable=False),
        sa.Column('player1_profile_id', sa.Integer(), nullable=False),
        sa.Column('player1_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player1_rating', sa.Integer(), nullable=False),
        sa.Column('player1_tier', sa.Integer(), nullable=False),
        sa.Column('player1_max_hp', sa.Integer(), nullable=False),
        sa.Column('player1_hp', sa.Integer(), nullable=False),
        sa.Column('player1_damage_dealt', sa.Integer(), nullable=False),
        sa.Column('player1_hits_landed', sa.Integer(), nullable=False),
        sa.Column('player1_skins', sa.JSON(), nullable=True),
        sa.Column('player1_is_bot', sa.Boolean(), nullable=False),
        sa.Column('player1_blocks_left', sa.Integer(), nullable=False),
        sa.Column('player1_hints_left', sa.Integer(), nullable=False),
        sa.Column('player1_shield_until_ms', sa.Integer(), nullable=True),
        sa.Column('player1_rerolls_left', sa.Integer(), nullable=False),
        sa.Column('player1_last_reroll_ms', sa.Integer(), nullable=True),
        sa.Column('player1_hand', sa.JSON(), nullable=True),
        sa.Column('player1_hints_revealed', sa.JSON(), nullable=True),
        sa.Column('player1_stats', sa.JSON(), nullable=True),
        sa.Column('player1_connected', sa.Boolean(), nullable=False),
        sa.Column('player2_profile_id', sa.Integer(), nullable=False),
        sa.Column('player2_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player2_rating', sa.Integer(), nullable=False),
        sa.Column('player2_tier', sa.Integer(), nullable=False),
        sa.Column('player2_max_hp', sa.Integer(), nullable=False),
        sa.Column('player2_hp', sa.Integer(), nullable=False),
        sa.Column('player2_damage_dealt', sa.Integer(), nullable=False),
        sa.Column('player2_hits_landed', sa.Integer(), nullable=False),
        sa.Column('player2_skins', sa.JSON(), nullable=True),
        sa.Column('player2_is_bot', sa.Boolean(), nullable=False),
        sa.Column('player2_blocks_left', sa.Integer(), nullable=False),
        sa.Column('player2_hints_left', sa.Integer(), nullable=False),
        sa.Column('player2_shield_until_ms', sa.Integer(), nullable=True),
        sa.Column('player2_rerolls_left', sa.Integer(), nullable=False),
        sa.Column('player2_last_reroll_ms', sa.Integer(), nullable=True),
        sa.Column('player2_hand', sa.JSON(), nullable=True),
        sa.Column('player2_hints_revealed', sa.JSON(), nullable=True),
        sa.Column('player2_stats', sa.JSON(), nullable=True),
        sa.Column('player2_connected', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_matches_mode', 'matches', ['mode'], unique=False)
    op.create_index('ix_matches_player1_profile_id', 'matches', ['player1_profile_id'], unique=False)
    op.create_index('ix_matches_player2_profile_id', 'matches', ['player2_profile_id'], unique=False)
    op.create_index('ix_matches_status', 'matches', ['status'], unique=False)

    op.create_table(
        'problems',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column('statement_md', sa.Text(), nullable=True),
        sa.Column('input_md', sa.Text(), nullable=True),
        sa.Column('output_md', sa.Text(), nullable=True),
        sa.Column('constraints_md', sa.Text(), nullable=True),
        sa.Column('biome', sqlmodel.sql.sqltypes.AutoString(length=24), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=False),
        sa.Column('base_damage', sa.Integer(), nullable=False),
        sa.Column('base_recoil', sa.Integer(), nullable=False),
        sa.Column('time_limit_ms', sa.Integer(), nullable=False),
        sa.Column('memory_mb', sa.Integer(), nullable=False),
        sa.Column('checker', sqlmodel.sql.sqltypes.AutoString(length=24), nullable=False),
        sa.Column('checker_script', sa.Text(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('hints', sa.JSON(), nullable=True),
        sa.Column('stubs', sa.JSON(), nullable=True),
        sa.Column('reference_solution', sa.Text(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
    )
    op.create_index('ix_problems_biome', 'problems', ['biome'], unique=False)
    op.create_index('ix_problems_slug', 'problems', ['slug'], unique=True)
    op.create_index('ix_problems_tier', 'problems', ['tier'], unique=False)

    op.create_table(
        'purchases',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('skin_id', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('idem_key', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('profile_id', 'idem_key'),
    )
    op.create_index('ix_purchases_profile_id', 'purchases', ['profile_id'], unique=False)

    op.create_table(
        'quest_progress',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('day', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('target', sa.Integer(), nullable=False),
        sa.Column('earned_at', sa.DateTime(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('profile_id', 'day', 'key'),
    )
    op.create_index('ix_quest_progress_profile_id', 'quest_progress', ['profile_id'], unique=False)

    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=True),
        sa.Column('target_profile_id', sa.Integer(), nullable=True),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_reports_reporter_id', 'reports', ['reporter_id'], unique=False)

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('username', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('username_lower', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('suspended_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_users_username_lower', 'users', ['username_lower'], unique=True)

    op.create_table(
        'match_events',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), sa.ForeignKey('matches.id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('t_ms', sa.Integer(), nullable=False),
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('visibility', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.UniqueConstraint('match_id', 'seq'),
    )
    op.create_index('ix_match_events_match_id', 'match_events', ['match_id'], unique=False)

    op.create_table(
        'profiles',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('peak_rating', sa.Integer(), nullable=False),
        sa.Column('wins', sa.Integer(), nullable=False),
        sa.Column('losses', sa.Integer(), nullable=False),
        sa.Column('draws', sa.Integer(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('equipped_card', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('equipped_avatar', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('equipped_arena', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=True),
        sa.Column('avatar_color', sqlmodel.sql.sqltypes.AutoString(length=9), nullable=False),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('is_bot', sa.Boolean(), nullable=False),
        sa.Column('personality', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column('bot_gain_today', sa.Integer(), nullable=False),
        sa.Column('casual_ap_today', sa.Integer(), nullable=False),
        sa.Column('daily_day', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column('last_win_day', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column('no_show_strikes', sa.Integer(), nullable=False),
        sa.Column('queue_ban_until', sa.DateTime(), nullable=True),
        sa.Column('counters', sa.JSON(), nullable=True),
        sa.Column('badges', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_profiles_display_name', 'profiles', ['display_name'], unique=False)

    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)

    op.create_table(
        'submissions',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), sa.ForeignKey('matches.id'), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('language', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('code', sa.Text(), nullable=True),
        sa.Column('cmd_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('verdict', sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column('failed_test', sa.Integer(), nullable=True),
        sa.Column('tests_passed', sa.Integer(), nullable=False),
        sa.Column('tests_total', sa.Integer(), nullable=False),
        sa.Column('time_ms', sa.Integer(), nullable=False),
        sa.Column('memory_kb', sa.Integer(), nullable=False),
        sa.Column('damage', sa.Integer(), nullable=False),
        sa.Column('recoil', sa.Integer(), nullable=False),
        sa.Column('blocked', sa.Boolean(), nullable=False),
        sa.Column('crit', sa.Boolean(), nullable=False),
        sa.Column('is_bot', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('profile_id', 'cmd_id'),
    )
    op.create_index('ix_submissions_match_id', 'submissions', ['match_id'], unique=False)
    op.create_index('ix_submissions_profile_id', 'submissions', ['profile_id'], unique=False)

    op.create_table(
        'test_cases',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('problem_id', sa.Integer(), sa.ForeignKey('problems.id'), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('expected_text', sa.Text(), nullable=True),
        sa.Column('is_sample', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('problem_id', 'idx'),
    )
    op.create_index('ix_test_cases_problem_id', 'test_cases', ['problem_id'], unique=False)

    op.create_table(
        'inventory',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('profiles.id'), nullable=False),
        sa.Column('skin_id', sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column('acquired_at', sa.DateTime(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.UniqueConstraint('profile_id', 'skin_id'),
    )
    op.create_index('ix_inventory_profile_id', 'inventory', ['profile_id'], unique=False)

    op.create_table(
        'rating_history',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('profiles.id'), nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=False),
        sa.Column('before', sa.Integer(), nullable=False),
        sa.Column('after', sa.Integer(), nullable=False),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=True),
        sa.Column('multiplier', sa.Integer(), nullable=False),
        sa.Column('voided', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_rating_history_match_id', 'rating_history', ['match_id'], unique=False)
    op.create_index('ix_rating_history_profile_created', 'rating_history', ['profile_id', 'created_at'], unique=False)
    op.create_index('ix_rating_history_profile_id', 'rating_history', ['profile_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_rating_history_match_id', table_name='rating_history')
    op.drop_index('ix_rating_history_profile_created', table_name='rating_history')
    op.drop_index('ix_rating_history_profile_id', table_name='rating_history')
    op.drop_table('rating_history')
    op.drop_index('ix_inventory_profile_id', table_name='inventory')
    op.drop_table('inventory')
    op.drop_index('ix_test_cases_problem_id', table_name='test_cases')
    op.drop_table('test_cases')
    op.drop_index('ix_submissions_match_id', table_name='submissions')
    op.drop_index('ix_submissions_profile_id', table_name='submissions')
    op.drop_table('submissions')
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_profiles_display_name', table_name='profiles')
    op.drop_table('profiles')
    op.drop_index('ix_match_events_match_id', table_name='match_events')
    op.drop_table('match_events')
    op.drop_index('ix_users_username_lower', table_name='users')
    op.drop_table('users')
    op.drop_index('ix_reports_reporter_id', table_name='reports')
    op.drop_table('reports')
    op.drop_index('ix_quest_progress_profile_id', table_name='quest_progress')
    op.drop_table('quest_progress')
    op.drop_index('ix_purchases_profile_id', table_name='purchases')
    op.drop_table('purchases')
    op.drop_index('ix_problems_biome', table_name='problems')
    op.drop_index('ix_problems_slug', table_name='problems')
    op.drop_index('ix_problems_tier', table_name='problems')
    op.drop_table('problems')
    op.drop_index('ix_matches_mode', table_name='matches')
    op.drop_index('ix_matches_player1_profile_id', table_name='matches')
    op.drop_index('ix_matches_player2_profile_id', table_name='matches')
    op.drop_index('ix_matches_status', table_name='matches')
    op.drop_table('matches')
    op.drop_index('ix_flags_match_id', table_name='flags')
    op.drop_index('ix_flags_profile_id', table_name='flags')
    op.drop_table('flags')
    op.drop_index('ix_drafts_match_id', table_name='drafts')
    op.drop_index('ix_drafts_profile_id', table_name='drafts')
    op.drop_table('drafts')
    op.drop_table('audit_log')
    op.drop_index('ix_achievements_profile_id', table_name='achievements')
    op.drop_table('achievements')
