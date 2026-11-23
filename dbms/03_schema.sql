-- =============================================================================
-- AlgoArena (cp_battle): the database schema for PostgreSQL (tested on 16.15)
--
-- These are the 17 tables the server uses (server/prisma/schema.prisma), with
-- the same table and column names, types, unique constraints and indexes the app creates.
-- Checked against the schema the app's own Prisma migration builds on
-- PostgreSQL 16: identical apart from what this file adds, which is
--   * the foreign keys and CHECK constraints the app's data already obeys but its
--     models leave implicit (the models declare 7 of the 23 foreign keys),
--   * column DEFAULTs matching the defaults the server fills in, and
--   * readable names for the unique constraints (the app lets PostgreSQL name
--     them, e.g. uq_test_cases_problem_idx is test_cases_problem_id_idx_key there).
--
-- Conventions
--   * Timestamps are UTC stored WITHOUT time zone (the app writes naive UTC).
--   * JSON columns hold whole documents the app reads and writes as one value
--     (a player's hand, per-match stats, an event payload). See 01_normalization.md.
--   * A "profile" is a player: people (user_id set) and bots (is_bot, user_id NULL).
--
-- Run:  psql -d algoarena -f 03_schema.sql
-- =============================================================================

BEGIN;

SET client_min_messages = warning;
DROP TABLE IF EXISTS reports, audit_log, flags, achievements, quest_progress, rating_history,
    purchases, inventory, drafts, match_events, submissions, matches, test_cases, problems,
    profiles, refresh_tokens, users CASCADE;

-- -----------------------------------------------------------------------------
-- Accounts
-- -----------------------------------------------------------------------------

-- A login. username keeps the user's capitalisation; username_lower is the
-- unique key every lookup uses (case-insensitive usernames).
CREATE TABLE users (
    id               SERIAL       PRIMARY KEY,
    username         VARCHAR(20)  NOT NULL,
    username_lower   VARCHAR(20)  NOT NULL,
    password_hash    VARCHAR      NOT NULL,                  -- Argon2id
    role             VARCHAR(16)  NOT NULL DEFAULT 'player',
    suspended_until  TIMESTAMP,
    created_at       TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT ck_users_lower CHECK (username_lower = lower(username)),
    CONSTRAINT ck_users_role  CHECK (role IN ('player', 'admin'))
);
CREATE UNIQUE INDEX ix_users_username_lower ON users (username_lower);   -- the key every login uses

-- Refresh tokens (only a SHA-256 of the token is stored). Rotated on every use;
-- reuse of a revoked token revokes the whole family.
CREATE TABLE refresh_tokens (
    id          SERIAL       PRIMARY KEY,
    user_id     INTEGER      NOT NULL REFERENCES users (id),
    token_hash  VARCHAR(64)  NOT NULL,
    expires_at  TIMESTAMP    NOT NULL,
    revoked_at  TIMESTAMP,
    created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);   -- alternate key

-- A player. One per user (user_id UNIQUE); bots and the practice dummy have no
-- user. Tier and max HP are not stored: they are derived from rating.
CREATE TABLE profiles (
    id                SERIAL       PRIMARY KEY,
    user_id           INTEGER      REFERENCES users (id),
    display_name      VARCHAR(32)  NOT NULL,
    rating            INTEGER      NOT NULL DEFAULT 1200,
    peak_rating       INTEGER      NOT NULL DEFAULT 1200,
    wins              INTEGER      NOT NULL DEFAULT 0,
    losses            INTEGER      NOT NULL DEFAULT 0,
    draws             INTEGER      NOT NULL DEFAULT 0,
    points            INTEGER      NOT NULL DEFAULT 0,       -- Arena Points (AP)
    equipped_card     VARCHAR(48)  NOT NULL DEFAULT 'card.classic',
    equipped_avatar   VARCHAR(48)  NOT NULL DEFAULT 'bean.plain',
    equipped_arena    VARCHAR(48),
    equipped_weapon   VARCHAR(48)  NOT NULL DEFAULT 'weapon.fireball',
    avatar_color      VARCHAR(9)   NOT NULL DEFAULT '#3b82f6',
    settings          JSON         DEFAULT '{}',             -- UI settings, code templates
    is_bot            BOOLEAN      NOT NULL DEFAULT FALSE,
    personality       VARCHAR(16),                           -- bots only
    bot_gain_today    INTEGER      NOT NULL DEFAULT 0,
    casual_ap_today   INTEGER      NOT NULL DEFAULT 0,
    daily_day         VARCHAR(10)  NOT NULL DEFAULT '',      -- UTC date the two counters above belong to
    last_win_day      VARCHAR(10)  NOT NULL DEFAULT '',
    no_show_strikes   INTEGER      NOT NULL DEFAULT 0,
    queue_ban_until   TIMESTAMP,
    counters          JSON         DEFAULT '{}',             -- career counters behind achievements
    badges            JSON         DEFAULT '[]',
    created_at        TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_profiles_user_id UNIQUE (user_id),
    -- (no peak_rating >= rating: an admin void can lift a rating back above the stored peak)
    CONSTRAINT ck_profiles_counts  CHECK (rating >= 0 AND wins >= 0 AND losses >= 0
                                          AND draws >= 0 AND points >= 0 AND no_show_strikes >= 0),
    CONSTRAINT ck_profiles_kind    CHECK (is_bot = (user_id IS NULL))   -- people have a login, bots do not
);
CREATE INDEX ix_profiles_display_name ON profiles (display_name);
-- From the timings in 05 (migration 0003_query_indexes). The partial WHERE clauses
-- repeat the app's own filters, so the planner can prove a query is covered.
CREATE INDEX ix_profiles_ladder ON profiles (rating DESC, lower(display_name))
    WHERE is_bot = false AND user_id IS NOT NULL;                -- all-time board in order, rank counts
CREATE INDEX ix_profiles_display_name_lower ON profiles (lower(display_name));   -- profile page by name
CREATE INDEX ix_profiles_bot_personality ON profiles (personality) WHERE is_bot = true;   -- pick a bot

-- -----------------------------------------------------------------------------
-- Problems
-- -----------------------------------------------------------------------------

-- A problem card. tier follows from rating (the same thresholds as players) and
-- base_damage/base_recoil from tier; they are stored so a dealt card is one row.
CREATE TABLE problems (
    id                  SERIAL        PRIMARY KEY,
    slug                VARCHAR(64)   NOT NULL,
    title               VARCHAR(120)  NOT NULL,
    statement_md        TEXT,
    input_md            TEXT,
    output_md           TEXT,
    constraints_md      TEXT,
    biome               VARCHAR(24)   NOT NULL,              -- bit | binary | general
    rating              INTEGER       NOT NULL,
    tier                INTEGER       NOT NULL,
    base_damage         INTEGER       NOT NULL,
    base_recoil         INTEGER       NOT NULL,
    time_limit_ms       INTEGER       NOT NULL DEFAULT 2000,
    memory_mb           INTEGER       NOT NULL DEFAULT 256,
    checker             VARCHAR(24)   NOT NULL DEFAULT 'exact',
    checker_script      TEXT,
    tags                JSON          DEFAULT '[]',
    hints               JSON          DEFAULT '[]',           -- three hints, in order
    stubs               JSON          DEFAULT '{}',           -- starting code per language
    reference_solution  TEXT,
    status              VARCHAR(16)   NOT NULL DEFAULT 'published',
    CONSTRAINT ck_problems_tier    CHECK (tier BETWEEN 1 AND 5),
    CONSTRAINT ck_problems_limits  CHECK (time_limit_ms > 0 AND memory_mb > 0 AND base_damage >= 0 AND base_recoil >= 0),
    CONSTRAINT ck_problems_checker CHECK (checker IN ('exact', 'tokens', 'float', 'unordered_lines', 'custom')),
    CONSTRAINT ck_problems_status  CHECK (status IN ('draft', 'published', 'retired'))
);
CREATE UNIQUE INDEX ix_problems_slug ON problems (slug);   -- alternate key
CREATE INDEX ix_problems_biome ON problems (biome);
CREATE INDEX ix_problems_tier ON problems (tier);

-- Test cases of a problem, numbered from 0. Samples are shown; the rest stay on the server.
CREATE TABLE test_cases (
    id             SERIAL   PRIMARY KEY,
    problem_id     INTEGER  NOT NULL REFERENCES problems (id),
    idx            INTEGER  NOT NULL,
    input_text     TEXT,
    expected_text  TEXT,
    is_sample      BOOLEAN  NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_test_cases_problem_idx UNIQUE (problem_id, idx),
    CONSTRAINT ck_test_cases_idx CHECK (idx >= 0)
);
CREATE INDEX ix_test_cases_problem_id ON test_cases (problem_id);

-- -----------------------------------------------------------------------------
-- Matches
-- -----------------------------------------------------------------------------

-- One row per match. The two sides are columns player1_* and player2_*: a match
-- always has exactly two, and the live engine saves both in one row update.
-- Name, rating, tier and max HP are a snapshot taken when the match was made.
CREATE TABLE matches (
    id                       VARCHAR(36)  PRIMARY KEY,       -- UUID
    mode                     VARCHAR(16)  NOT NULL,
    map                      VARCHAR(16)  NOT NULL,
    status                   VARCHAR(16)  NOT NULL DEFAULT 'starting',
    seed                     INTEGER      NOT NULL,
    stage_theme              VARCHAR(48)  NOT NULL DEFAULT 'arena.bit',
    stage_owner_side         INTEGER,
    created_at               TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    start_time               TIMESTAMP,
    end_time                 TIMESTAMP,
    elapsed_ms               INTEGER      NOT NULL DEFAULT 0,
    end_reason               VARCHAR(16),
    outcome                  VARCHAR(16),
    winner_side              INTEGER,
    labels                   JSON         DEFAULT '{}',      -- {"1": "victory", "2": "defeat"}
    result                   JSON         DEFAULT '{}',      -- the result screen: rating steps, AP, unlocks
    decks                    JSON         DEFAULT '{}',      -- problem ids per tier, shuffled with seed
    last_seq                 INTEGER      NOT NULL DEFAULT 0, -- last match_events.seq written

    player1_profile_id       INTEGER      NOT NULL REFERENCES profiles (id),
    player1_name             VARCHAR      NOT NULL DEFAULT '',
    player1_rating           INTEGER      NOT NULL DEFAULT 0,
    player1_tier             INTEGER      NOT NULL DEFAULT 1,
    player1_max_hp           INTEGER      NOT NULL DEFAULT 0,
    player1_hp               INTEGER      NOT NULL DEFAULT 0,
    player1_damage_dealt     INTEGER      NOT NULL DEFAULT 0,
    player1_hits_landed      INTEGER      NOT NULL DEFAULT 0,
    player1_skins            JSON         DEFAULT '{}',
    player1_is_bot           BOOLEAN      NOT NULL DEFAULT FALSE,
    player1_blocks_left      INTEGER      NOT NULL DEFAULT 0,
    player1_hints_left       INTEGER      NOT NULL DEFAULT 0,
    player1_shield_until_ms  INTEGER,
    player1_rerolls_left     INTEGER      NOT NULL DEFAULT 0,
    player1_last_reroll_ms   INTEGER,
    player1_hand             JSON         DEFAULT '{}',      -- the four cards in hand
    player1_hints_revealed   JSON         DEFAULT '{}',
    player1_stats            JSON         DEFAULT '{}',      -- crits, backfires, fastest solve, ...
    player1_connected        BOOLEAN      NOT NULL DEFAULT FALSE,

    player2_profile_id       INTEGER      NOT NULL REFERENCES profiles (id),
    player2_name             VARCHAR      NOT NULL DEFAULT '',
    player2_rating           INTEGER      NOT NULL DEFAULT 0,
    player2_tier             INTEGER      NOT NULL DEFAULT 1,
    player2_max_hp           INTEGER      NOT NULL DEFAULT 0,
    player2_hp               INTEGER      NOT NULL DEFAULT 0,
    player2_damage_dealt     INTEGER      NOT NULL DEFAULT 0,
    player2_hits_landed      INTEGER      NOT NULL DEFAULT 0,
    player2_skins            JSON         DEFAULT '{}',
    player2_is_bot           BOOLEAN      NOT NULL DEFAULT FALSE,
    player2_blocks_left      INTEGER      NOT NULL DEFAULT 0,
    player2_hints_left       INTEGER      NOT NULL DEFAULT 0,
    player2_shield_until_ms  INTEGER,
    player2_rerolls_left     INTEGER      NOT NULL DEFAULT 0,
    player2_last_reroll_ms   INTEGER,
    player2_hand             JSON         DEFAULT '{}',
    player2_hints_revealed   JSON         DEFAULT '{}',
    player2_stats            JSON         DEFAULT '{}',
    player2_connected        BOOLEAN      NOT NULL DEFAULT FALSE,

    CONSTRAINT ck_matches_mode       CHECK (mode IN ('ranked', 'bot', 'practice', 'friendly', 'team')),
    CONSTRAINT ck_matches_map        CHECK (map IN ('bit', 'binary', 'prestige')),
    CONSTRAINT ck_matches_status     CHECK (status IN ('starting', 'live', 'finished', 'aborted')),
    CONSTRAINT ck_matches_end_reason CHECK (end_reason IN ('ko', 'timer', 'forfeit', 'disconnect', 'aborted')),
    CONSTRAINT ck_matches_outcome    CHECK (outcome IN ('win', 'draw', 'aborted')),
    CONSTRAINT ck_matches_winner_side CHECK (winner_side IN (1, 2)),
    CONSTRAINT ck_matches_stage_side CHECK (stage_owner_side IN (1, 2)),
    CONSTRAINT ck_matches_winner     CHECK ((outcome = 'win') = (winner_side IS NOT NULL)),
    CONSTRAINT ck_matches_two_people CHECK (player1_profile_id <> player2_profile_id),
    CONSTRAINT ck_matches_hp         CHECK (player1_hp BETWEEN 0 AND player1_max_hp AND player2_hp BETWEEN 0 AND player2_max_hp),
    CONSTRAINT ck_matches_tiers      CHECK (player1_tier BETWEEN 1 AND 5 AND player2_tier BETWEEN 1 AND 5),
    CONSTRAINT ck_matches_ended      CHECK (status NOT IN ('finished', 'aborted') OR end_reason IS NOT NULL)
);
CREATE INDEX ix_matches_mode ON matches (mode);
CREATE INDEX ix_matches_status ON matches (status);
CREATE INDEX ix_matches_player1_profile_id ON matches (player1_profile_id);
CREATE INDEX ix_matches_player2_profile_id ON matches (player2_profile_id);
CREATE INDEX ix_matches_created_at ON matches (created_at);                      -- admin: latest matches
CREATE INDEX ix_matches_finished_end_time ON matches (end_time)
    WHERE status = 'finished';                                   -- weekly board
CREATE INDEX ix_matches_map_winners ON matches (map)
    INCLUDE (winner_side, player1_profile_id, player2_profile_id)
    WHERE status = 'finished' AND winner_side IS NOT NULL;       -- map board, answered from the index alone

-- Every submission a player (or a bot) makes in a match. cmd_id makes a retried
-- submit idempotent: (profile_id, cmd_id) is unique.
CREATE TABLE submissions (
    id            SERIAL       PRIMARY KEY,
    match_id      VARCHAR(36)  NOT NULL REFERENCES matches (id),
    profile_id    INTEGER      NOT NULL REFERENCES profiles (id),
    problem_id    INTEGER      NOT NULL REFERENCES problems (id),
    slot          INTEGER      NOT NULL,
    language      VARCHAR(16)  NOT NULL,
    code          TEXT,
    cmd_id        VARCHAR(64)  NOT NULL,
    status        VARCHAR(16)  NOT NULL DEFAULT 'judging',
    verdict       VARCHAR(8),
    failed_test   INTEGER,
    tests_passed  INTEGER      NOT NULL DEFAULT 0,
    tests_total   INTEGER      NOT NULL DEFAULT 0,
    time_ms       INTEGER      NOT NULL DEFAULT 0,
    memory_kb     INTEGER      NOT NULL DEFAULT 0,
    damage        INTEGER      NOT NULL DEFAULT 0,
    recoil        INTEGER      NOT NULL DEFAULT 0,
    blocked       BOOLEAN      NOT NULL DEFAULT FALSE,
    crit          BOOLEAN      NOT NULL DEFAULT FALSE,
    is_bot        BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_submissions_profile_cmd UNIQUE (profile_id, cmd_id),
    CONSTRAINT ck_submissions_slot     CHECK (slot BETWEEN 0 AND 3),
    CONSTRAINT ck_submissions_status   CHECK (status IN ('judging', 'done', 'void')),
    CONSTRAINT ck_submissions_verdict  CHECK (verdict IN ('AC', 'WA', 'TLE', 'MLE', 'RE', 'CE', 'OLE', 'SE')),
    CONSTRAINT ck_submissions_judged   CHECK (status <> 'done' OR verdict IS NOT NULL),
    CONSTRAINT ck_submissions_numbers  CHECK (tests_passed BETWEEN 0 AND tests_total AND damage >= 0 AND recoil >= 0)
);
CREATE INDEX ix_submissions_match_id ON submissions (match_id);
CREATE INDEX ix_submissions_profile_id ON submissions (profile_id);

-- The append-only event log of a match: it can rebuild any match and drives
-- reconnects and replays. visibility: both | p1 | p2 | spectator.
CREATE TABLE match_events (
    id          SERIAL       PRIMARY KEY,
    match_id    VARCHAR(36)  NOT NULL REFERENCES matches (id),
    seq         INTEGER      NOT NULL,
    t_ms        INTEGER      NOT NULL,
    type        VARCHAR(40)  NOT NULL,
    payload     JSON         DEFAULT '{}',
    visibility  VARCHAR(10)  NOT NULL DEFAULT 'both',
    CONSTRAINT uq_match_events_match_seq UNIQUE (match_id, seq),
    CONSTRAINT ck_match_events_seq        CHECK (seq >= 1 AND t_ms >= 0),
    CONSTRAINT ck_match_events_visibility CHECK (visibility IN ('both', 'p1', 'p2', 'spectator'))
);
CREATE INDEX ix_match_events_match_id ON match_events (match_id);

-- Unsaved code in the editor, per match, player, slot and language. Deleted
-- when the card is submitted and when the match ends.
CREATE TABLE drafts (
    id            SERIAL       PRIMARY KEY,
    match_id      VARCHAR(36)  NOT NULL REFERENCES matches (id),
    profile_id    INTEGER      NOT NULL REFERENCES profiles (id),
    slot          INTEGER      NOT NULL,
    language      VARCHAR(16)  NOT NULL,
    code          TEXT,
    problem_slug  VARCHAR(64)  NOT NULL DEFAULT '',
    updated_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_drafts_key UNIQUE (match_id, profile_id, slot, language),
    CONSTRAINT ck_drafts_slot CHECK (slot BETWEEN 0 AND 3)
);
CREATE INDEX ix_drafts_match_id ON drafts (match_id);
CREATE INDEX ix_drafts_profile_id ON drafts (profile_id);

-- -----------------------------------------------------------------------------
-- Progress, items and the economy
-- -----------------------------------------------------------------------------

-- Skins a player owns. skin_id names a manifest in shared/skins/*.json (the
-- skin catalogue lives in files, not in the database).
CREATE TABLE inventory (
    id           SERIAL       PRIMARY KEY,
    profile_id   INTEGER      NOT NULL REFERENCES profiles (id),
    skin_id      VARCHAR(48)  NOT NULL,
    acquired_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    source       VARCHAR(16)  NOT NULL DEFAULT 'default',
    CONSTRAINT uq_inventory_profile_skin UNIQUE (profile_id, skin_id),
    CONSTRAINT ck_inventory_source CHECK (source IN ('default', 'tier', 'ap', 'achievement', 'quest', 'admin'))
);
CREATE INDEX ix_inventory_profile_id ON inventory (profile_id);

-- Skins bought with Arena Points. idem_key makes a retried purchase charge once.
CREATE TABLE purchases (
    id          SERIAL       PRIMARY KEY,
    profile_id  INTEGER      NOT NULL REFERENCES profiles (id),
    skin_id     VARCHAR(48)  NOT NULL,
    idem_key    VARCHAR(64)  NOT NULL,
    price       INTEGER      NOT NULL,                       -- what was paid then
    created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_purchases_profile_idem UNIQUE (profile_id, idem_key),
    CONSTRAINT ck_purchases_price CHECK (price >= 0)
);
CREATE INDEX ix_purchases_profile_id ON purchases (profile_id);

-- One row per rated player per match. An admin "void" reverses it (voided = true).
CREATE TABLE rating_history (
    id          SERIAL       PRIMARY KEY,
    profile_id  INTEGER      NOT NULL REFERENCES profiles (id),
    match_id    VARCHAR(36)  NOT NULL REFERENCES matches (id),
    before      INTEGER      NOT NULL,
    after       INTEGER      NOT NULL,
    delta       INTEGER      NOT NULL,
    steps       JSON         DEFAULT '[]',                   -- the rating breakdown shown on the result screen
    multiplier  INTEGER      NOT NULL DEFAULT 100,           -- percent applied (mode, rematch)
    voided      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT ck_rating_history_delta CHECK (delta = after - before)
);
CREATE INDEX ix_rating_history_profile_id ON rating_history (profile_id);
CREATE INDEX ix_rating_history_match_id ON rating_history (match_id);
CREATE INDEX ix_rating_history_profile_created ON rating_history (profile_id, created_at);

-- Daily quest progress: one row per player, UTC day and quest key.
CREATE TABLE quest_progress (
    id          SERIAL       PRIMARY KEY,
    profile_id  INTEGER      NOT NULL REFERENCES profiles (id),
    day         VARCHAR(10)  NOT NULL,                       -- YYYY-MM-DD (UTC)
    key         VARCHAR(32)  NOT NULL,
    progress    INTEGER      NOT NULL DEFAULT 0,
    target      INTEGER      NOT NULL DEFAULT 1,
    earned_at   TIMESTAMP,
    claimed_at  TIMESTAMP,
    CONSTRAINT uq_quest_progress_key UNIQUE (profile_id, day, key),
    CONSTRAINT ck_quest_progress CHECK (progress BETWEEN 0 AND target AND (claimed_at IS NULL OR earned_at IS NOT NULL))
);
CREATE INDEX ix_quest_progress_profile_id ON quest_progress (profile_id);

-- Achievements a player has earned (the definitions are in shared/game-config.json).
CREATE TABLE achievements (
    id          SERIAL       PRIMARY KEY,
    profile_id  INTEGER      NOT NULL REFERENCES profiles (id),
    key         VARCHAR(32)  NOT NULL,
    progress    INTEGER      NOT NULL DEFAULT 0,
    earned_at   TIMESTAMP,
    claimed_at  TIMESTAMP,
    CONSTRAINT uq_achievements_profile_key UNIQUE (profile_id, key)
);
CREATE INDEX ix_achievements_profile_id ON achievements (profile_id);

-- -----------------------------------------------------------------------------
-- Moderation
-- -----------------------------------------------------------------------------

-- Automatic flags raised during matches (for example repeated judge system errors).
CREATE TABLE flags (
    id          SERIAL       PRIMARY KEY,
    match_id    VARCHAR(36)  REFERENCES matches (id),
    profile_id  INTEGER      REFERENCES profiles (id),
    kind        VARCHAR(32)  NOT NULL,
    severity    INTEGER      NOT NULL DEFAULT 1,
    details     JSON         DEFAULT '{}',
    status      VARCHAR(16)  NOT NULL DEFAULT 'open',
    created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT ck_flags_status CHECK (status IN ('open', 'dismissed', 'warned', 'actioned'))
);
CREATE INDEX ix_flags_match_id ON flags (match_id);
CREATE INDEX ix_flags_profile_id ON flags (profile_id);

-- Every admin action.
CREATE TABLE audit_log (
    id          SERIAL       PRIMARY KEY,
    actor_id    INTEGER      REFERENCES users (id),
    action      VARCHAR(48)  NOT NULL,
    target      VARCHAR(64)  NOT NULL DEFAULT '',
    details     JSON         DEFAULT '{}',
    created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

-- Player reports about a match or an opponent.
CREATE TABLE reports (
    id                 SERIAL        PRIMARY KEY,
    reporter_id        INTEGER       NOT NULL REFERENCES profiles (id),
    match_id           VARCHAR(36)   REFERENCES matches (id),
    target_profile_id  INTEGER       REFERENCES profiles (id),
    reason             VARCHAR(500)  NOT NULL,
    created_at         TIMESTAMP     NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX ix_reports_reporter_id ON reports (reporter_id);

COMMIT;
