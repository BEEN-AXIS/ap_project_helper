-- =============================================================================
-- AlgoArena (cp_battle): every query the app runs, in PostgreSQL
--
-- Each block is one query: a number, -- READ or -- WRITE, what it is for, and
-- where the backend runs it (file:line under backend/app/). The backend uses
-- SQLAlchemy, so its SQL is generated; these statements do the same work.
-- Where the app makes several round trips for one job (look up a user, then
-- the profile, then the skins), the query here does it in one statement with a
-- JOIN, a data-modifying CTE or INSERT ... SELECT, and the header says so.
--
-- Values are written in as literals so the file runs as it is; the app binds
-- them as parameters. They match the benchmark data (tools/benchmark_data.sql):
--   player 26 ('player_26', rating 1367); their latest ranked match
--   '9348a163-6e39-4f78-8557-09984d57dc04' against player 3866; a live match
--   '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f' between players 101 and 5001; "now"
--   is 2026-11-23 12:00 UTC.
--
-- The whole file runs in one transaction and rolls back, so it leaves the data
-- as it found it:   psql -d algoarena -f 04_queries.sql
-- =============================================================================

\set ON_ERROR_STOP on
-- Q27 returns 6 MB of test data. psql's default aligned display pads every row
-- to the widest value, which turns that into gigabytes on screen: print unaligned.
\pset format unaligned

BEGIN;

-- #############################################################################
-- Accounts and sessions
-- #############################################################################

-- =============================================================================
-- Q01 · READ · Sign up: is the username taken?
-- App: api/auth.py:77 (POST /auth/signup); also seed.py:72, api/admin.py:132
-- =============================================================================
-- READ
SELECT id
FROM users
WHERE username_lower = 'new_player';

-- =============================================================================
-- Q02 · WRITE · Sign up: create the user, their profile and their default skins
-- App: api/auth.py:80, :84 and seed.py:96-97 (grant_defaults). The app does an
-- INSERT, an INSERT and ten SELECT-then-INSERTs; here it is one statement.
-- =============================================================================
-- WRITE
WITH new_user AS (
    INSERT INTO users (username, username_lower, password_hash)
    VALUES ('New_Player', 'new_player', '$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo')
    RETURNING id, username
), new_profile AS (
    INSERT INTO profiles (user_id, display_name, rating, peak_rating, avatar_color)
    SELECT id, username, 1200, 1200, '#3b82f6'
    FROM new_user
    RETURNING id
), defaults AS (
    INSERT INTO inventory (profile_id, skin_id, source)
    SELECT p.id, d.skin_id, 'default'
    FROM new_profile p
    CROSS JOIN unnest(ARRAY['arena.bit', 'arena.circuit', 'arena.prestige', 'bean.plain', 'card.classic',
                            'weapon.arrows', 'weapon.fireball', 'weapon.gun', 'weapon.lightning', 'weapon.spear']) AS d (skin_id)
    ON CONFLICT (profile_id, skin_id) DO NOTHING
)
SELECT u.id AS user_id, p.id AS profile_id
FROM new_user u
CROSS JOIN new_profile p;

-- =============================================================================
-- Q03 · READ · Log in: the user and their profile
-- App: api/auth.py:104 and :113 (two lookups); here one JOIN.
-- =============================================================================
-- READ
SELECT u.id AS user_id, u.password_hash, u.role, u.suspended_until,
       p.id AS profile_id, p.display_name, p.rating
FROM users u
JOIN profiles p ON p.user_id = u.id
WHERE u.username_lower = 'player_26';

-- =============================================================================
-- Q04 · READ · The signed-in player (GET /me and every session payload):
-- profile, account role and owned skins
-- App: services/profiles.py:30-31 via api/players.py:59 and api/auth.py
-- (_session_payload). The app reads the profile, the inventory and the user
-- separately; here one LEFT JOIN with the skins aggregated.
-- =============================================================================
-- READ
SELECT p.id, p.display_name, p.rating, p.peak_rating, p.wins, p.losses, p.draws, p.points,
       p.equipped_card, p.equipped_avatar, p.equipped_arena, p.equipped_weapon, p.avatar_color,
       p.settings, p.counters, p.badges, p.queue_ban_until,
       u.username, u.role,
       array_agg(i.skin_id ORDER BY i.skin_id) FILTER (WHERE i.skin_id IS NOT NULL) AS owned_skins
FROM profiles p
JOIN users u ON u.id = p.user_id
LEFT JOIN inventory i ON i.profile_id = p.id
WHERE p.id = 26
GROUP BY p.id, u.id;

-- =============================================================================
-- Q05 · WRITE · Issue a refresh token (only its SHA-256 is stored)
-- App: api/auth.py:50 (_issue_refresh, on signup, login and refresh)
-- =============================================================================
-- WRITE
INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
VALUES (26, '5d41402abc4b2a76b9719d911017c592aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        (now() AT TIME ZONE 'utc') + interval '30 days');

-- =============================================================================
-- Q06 · READ · Refresh: the token, its user and their profile
-- App: api/auth.py:129, :141 and :145 (three lookups); here one JOIN.
-- =============================================================================
-- READ
SELECT t.id AS token_id, t.expires_at, t.revoked_at,
       u.id AS user_id, u.role, u.suspended_until,
       p.id AS profile_id
FROM refresh_tokens t
JOIN users u ON u.id = t.user_id
JOIN profiles p ON p.user_id = u.id
WHERE t.token_hash = '63cb14d415156152101161aa436b76b38f0fdab62416603f916dbc448895b357';

-- =============================================================================
-- Q07 · WRITE · Refresh with a token that was already used: revoke the whole family
-- App: api/auth.py:134-136 (SELECT the live tokens, then UPDATE each); here one UPDATE.
-- =============================================================================
-- WRITE
UPDATE refresh_tokens
SET revoked_at = now() AT TIME ZONE 'utc'
WHERE user_id = 26
  AND revoked_at IS NULL;

-- =============================================================================
-- Q08 · WRITE · Refresh: rotate (revoke the token that was just used)
-- App: api/auth.py:140
-- =============================================================================
-- WRITE
UPDATE refresh_tokens
SET revoked_at = now() AT TIME ZONE 'utc'
WHERE id = 126;

-- =============================================================================
-- Q09 · WRITE · Log out: revoke the cookie's token
-- App: api/auth.py:160-163 (SELECT by hash, then UPDATE); here one UPDATE.
-- =============================================================================
-- WRITE
UPDATE refresh_tokens
SET revoked_at = now() AT TIME ZONE 'utc'
WHERE token_hash = '75f5a8b1be256ecd88bf5eb7ab5e078fcdb020fd46fdc1c6e82803d5e90c13ad'
  AND revoked_at IS NULL;

-- #############################################################################
-- Home and profile pages
-- #############################################################################

-- =============================================================================
-- Q10 · READ · Home: my last 8 finished or aborted matches
-- App: api/players.py:62-64 (GET /me)
-- =============================================================================
-- READ
SELECT id, mode, map, status, created_at, end_reason, labels, result,
       player1_profile_id, player1_name, player1_tier, player1_is_bot,
       player2_profile_id, player2_name, player2_tier, player2_is_bot
FROM matches
WHERE (player1_profile_id = 26 OR player2_profile_id = 26)
  AND status IN ('finished', 'aborted')
ORDER BY created_at DESC
LIMIT 8;

-- =============================================================================
-- Q11 · READ · Home: today's quest progress
-- App: api/players.py:47 (_quests, in GET /me and GET /quests)
-- =============================================================================
-- READ
SELECT key, progress, target, earned_at, claimed_at
FROM quest_progress
WHERE profile_id = 26
  AND day = '2026-11-23';

-- =============================================================================
-- Q12 · WRITE · Save settings (volumes, music, code templates)
-- App: api/players.py:103-106 (PUT /me/settings)
-- =============================================================================
-- WRITE
UPDATE profiles
SET settings = '{"master": 0.8, "music": true, "musicVolume": 0.5, "codeLanguage": "cpp",
                 "templates": {"cpp": "#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n}\n"}}'
WHERE id = 26;

-- =============================================================================
-- Q13 · WRITE · Claim a finished quest and pay its Arena Points
-- App: api/players.py:120-131 (SELECT the quest, SELECT the profile, then two
-- UPDATEs); here one statement: the quest is marked claimed only if it was
-- earned and not yet claimed, and the points are added through a join on it.
-- =============================================================================
-- WRITE
WITH claimed AS (
    UPDATE quest_progress
    SET claimed_at = now() AT TIME ZONE 'utc'
    WHERE profile_id = 30 AND day = '2026-11-23' AND key = 'first_blood'
      AND earned_at IS NOT NULL
      AND claimed_at IS NULL
    RETURNING profile_id
)
UPDATE profiles p
SET points = p.points + 20
FROM claimed c
WHERE p.id = c.profile_id
RETURNING p.points;

-- =============================================================================
-- Q14 · READ · Profile page: find the player by name (case-insensitive)
-- App: api/players.py:173 (GET /profiles/{username})
-- =============================================================================
-- READ
SELECT *
FROM profiles
WHERE lower(display_name) = lower('Player_26')
  AND NOT is_bot
LIMIT 1;

-- =============================================================================
-- Q15 · READ · Profile page: the last 50 rating changes (the rating chart)
-- App: api/players.py:176-177
-- =============================================================================
-- READ
SELECT match_id, before, after, delta, created_at
FROM rating_history
WHERE profile_id = 26
  AND NOT voided
ORDER BY created_at DESC
LIMIT 50;

-- =============================================================================
-- Q16 · READ · Profile page: battle history (last 20 finished or aborted)
-- App: api/players.py:178-180
-- =============================================================================
-- READ
SELECT id, mode, map, status, created_at, end_reason, labels, result,
       player1_profile_id, player1_name, player1_tier, player1_is_bot,
       player2_profile_id, player2_name, player2_tier, player2_is_bot
FROM matches
WHERE (player1_profile_id = 26 OR player2_profile_id = 26)
  AND status IN ('finished', 'aborted')
ORDER BY created_at DESC
LIMIT 20;

-- =============================================================================
-- Q17 · READ · Profile page: accuracy (accepted out of judged)
-- App: api/players.py:181 and :182 (two COUNTs); here one scan with FILTER.
-- =============================================================================
-- READ
SELECT count(*) FILTER (WHERE verdict = 'AC')  AS accepted,
       count(*) FILTER (WHERE status = 'done') AS judged
FROM submissions
WHERE profile_id = 26;

-- =============================================================================
-- Q18 · READ · Career stats: up to 1000 finished matches (streaks, maps, activity)
-- App: services/stats.py:113-115. The app reads whole rows; these are the
-- columns the summary uses.
-- =============================================================================
-- READ
SELECT id, mode, map, created_at, end_reason, outcome, winner_side, elapsed_ms,
       player1_profile_id, player1_damage_dealt, player1_hits_landed, player1_stats,
       player2_profile_id, player2_damage_dealt, player2_hits_landed, player2_stats
FROM matches
WHERE (player1_profile_id = 26 OR player2_profile_id = 26)
  AND status = 'finished'
ORDER BY created_at DESC
LIMIT 1000;

-- =============================================================================
-- Q19 · READ · Career stats: submissions by language, by verdict, and in total
-- App: services/stats.py:119-127 (reads every row and counts in Python);
-- here GROUPING SETS return all three counts in one pass.
-- =============================================================================
-- READ
SELECT language, verdict, count(*) AS n
FROM submissions
WHERE profile_id = 26
  AND status = 'done'
GROUP BY GROUPING SETS ((language), (verdict), ())
ORDER BY language NULLS LAST, verdict NULLS LAST;

-- =============================================================================
-- Q20 · READ · Career stats: distinct problems solved, by topic and tier
-- App: services/stats.py:119-134 (joins submission rows to the problem cache
-- in Python); here a JOIN to problems.
-- =============================================================================
-- READ
SELECT pr.biome, pr.tier, count(DISTINCT s.problem_id) AS solved
FROM submissions s
JOIN problems pr ON pr.id = s.problem_id
WHERE s.profile_id = 26
  AND s.status = 'done'
  AND s.verdict = 'AC'
GROUP BY pr.biome, pr.tier
ORDER BY pr.biome, pr.tier;

-- =============================================================================
-- Q21 · READ · A player's achievements
-- App: services/stats.py:142, engine/finish.py:183, skins/service.py:25
-- =============================================================================
-- READ
SELECT key, progress, earned_at, claimed_at
FROM achievements
WHERE profile_id = 26;

-- =============================================================================
-- Q22 · READ · The skins a player owns
-- App: skins/service.py:17 (owned), services/stats.py:156, services/profiles.py:30
-- =============================================================================
-- READ
SELECT skin_id
FROM inventory
WHERE profile_id = 26;

-- =============================================================================
-- Q23 · READ · Rank among people: how many rate higher, and how many there are
-- App: services/stats.py:161 and :163 (two COUNTs); here one self-join.
-- =============================================================================
-- READ
SELECT count(*) FILTER (WHERE o.rating > me.rating) + 1 AS position,
       count(*)                                         AS players
FROM profiles me
JOIN profiles o ON NOT o.is_bot AND o.user_id IS NOT NULL
WHERE me.id = 26;

-- #############################################################################
-- Leaderboards
-- #############################################################################

-- =============================================================================
-- Q24 · READ · Leaderboard, all time: the top 100 by rating
-- App: api/players.py:203-229 (loads every human profile and sorts in Python);
-- here the database ranks. Tier is derived from rating (it is not stored).
-- Ordering by the same keys as the window (not by "rank") gives the same rows
-- and lets an index on (rating DESC, lower(display_name)) stop after 100.
-- =============================================================================
-- READ
SELECT row_number() OVER (ORDER BY rating DESC, lower(display_name)) AS rank,
       id AS profile_id, display_name AS name, rating,
       CASE WHEN rating >= 1900 THEN 5 WHEN rating >= 1600 THEN 4 WHEN rating >= 1400 THEN 3
            WHEN rating >= 1200 THEN 2 ELSE 1 END AS tier,
       rating AS score, wins, losses
FROM profiles
WHERE NOT is_bot
  AND user_id IS NOT NULL
ORDER BY rating DESC, lower(display_name)
LIMIT 100;

-- =============================================================================
-- Q25 · READ · Leaderboard, this week: rating gained in matches that ended in
-- the last 7 days
-- App: api/players.py:203-222 (reads the matches, sums result.sides[n].delta
-- per player in Python); here each match is split into its two sides with a
-- LATERAL VALUES list and joined to profiles.
-- =============================================================================
-- READ
SELECT row_number() OVER (ORDER BY sum(x.delta) DESC, lower(p.display_name)) AS rank,
       p.id AS profile_id, p.display_name AS name, p.rating,
       sum(x.delta) AS score, p.wins, p.losses
FROM matches m
CROSS JOIN LATERAL (VALUES (m.player1_profile_id, (m.result -> 'sides' -> '1' ->> 'delta')::int),
                           (m.player2_profile_id, (m.result -> 'sides' -> '2' ->> 'delta')::int)) AS x (profile_id, delta)
JOIN profiles p ON p.id = x.profile_id AND NOT p.is_bot AND p.user_id IS NOT NULL
WHERE m.status = 'finished'
  AND m.end_time >= timestamp '2026-11-16 12:00'
  AND x.delta IS NOT NULL
GROUP BY p.id
ORDER BY rank
LIMIT 100;

-- =============================================================================
-- Q26 · READ · Leaderboard for one map: most wins there
-- App: api/players.py:209-218 (map filter); here the winner's profile is joined
-- through the side that won.
-- =============================================================================
-- READ
SELECT row_number() OVER (ORDER BY count(*) DESC, lower(p.display_name)) AS rank,
       p.id AS profile_id, p.display_name AS name, p.rating, count(*) AS score
FROM matches m
JOIN profiles p ON p.id = CASE m.winner_side WHEN 1 THEN m.player1_profile_id ELSE m.player2_profile_id END
WHERE m.status = 'finished'
  AND m.map = 'prestige'
  AND m.winner_side IS NOT NULL
  AND NOT p.is_bot
  AND p.user_id IS NOT NULL
GROUP BY p.id
ORDER BY rank
LIMIT 100;

-- #############################################################################
-- Problems
-- #############################################################################

-- =============================================================================
-- Q27 · READ · Load the problem cache: every published problem with its tests
-- App: services/problems.py:78 and :80 (one query for the problems, then one
-- per problem for its tests, 1 + N round trips); here one LEFT JOIN.
-- =============================================================================
-- READ
SELECT p.id, p.slug, p.title, p.biome, p.rating, p.tier, p.base_damage, p.base_recoil,
       p.time_limit_ms, p.memory_mb, p.checker, p.statement_md, p.hints, p.stubs,
       t.idx, t.input_text, t.expected_text, t.is_sample
FROM problems p
LEFT JOIN test_cases t ON t.problem_id = p.id
WHERE p.status = 'published'
ORDER BY p.id, t.idx;

-- =============================================================================
-- Q28 · READ · Practice browser: every problem with whether I have solved it
-- App: api/players.py:247 (the solved set; the list itself comes from the
-- cache); here the list and the solved flag in one LEFT JOIN.
-- =============================================================================
-- READ
SELECT p.slug, p.title, p.biome, p.tier, p.rating, (s.problem_id IS NOT NULL) AS solved
FROM problems p
LEFT JOIN (SELECT DISTINCT problem_id
           FROM submissions
           WHERE profile_id = 26 AND verdict = 'AC') s ON s.problem_id = p.id
WHERE p.status = 'published'
ORDER BY p.biome, p.tier, p.slug;

-- #############################################################################
-- Matchmaking and creating a match
-- #############################################################################

-- =============================================================================
-- Q29 · READ · Matchmaking: both players of an accepted pairing
-- App: engine/matchmaker.py:248 (two primary-key lookups); here one IN list.
-- Also: api/matches.py:72 (the caller's profile before a bot or practice match)
-- =============================================================================
-- READ
SELECT id, display_name, rating, is_bot, equipped_card, equipped_avatar, equipped_arena,
       equipped_weapon, avatar_color, queue_ban_until
FROM profiles
WHERE id IN (26, 3866);

-- =============================================================================
-- Q30 · READ · Pick a bot opponent by personality
-- App: engine/service.py:209; also seed.py:104 (ensure_bots)
-- =============================================================================
-- READ
SELECT *
FROM profiles
WHERE is_bot
  AND personality = 'gambler'
LIMIT 1;

-- =============================================================================
-- Q31 · WRITE · Create a match: both players' snapshots, hands and the decks
-- App: engine/service.py:161 (and :186 for bot-vs-bot)
-- =============================================================================
-- WRITE
INSERT INTO matches (id, mode, map, status, seed, stage_theme, stage_owner_side, decks,
                     player1_profile_id, player1_name, player1_rating, player1_tier, player1_max_hp, player1_hp,
                     player1_skins, player1_is_bot, player1_blocks_left, player1_hints_left, player1_rerolls_left, player1_hand,
                     player2_profile_id, player2_name, player2_rating, player2_tier, player2_max_hp, player2_hp,
                     player2_skins, player2_is_bot, player2_blocks_left, player2_hints_left, player2_rerolls_left, player2_hand)
VALUES ('b5e0c0de-1111-4222-8333-444455556666', 'ranked', 'bit', 'starting', 912345, 'arena.neon', 1,
        '{"1": [1, 2, 3, 4], "2": [5, 6, 7, 8], "3": [9, 10, 11, 12], "4": [13, 14, 15], "5": [16, 17]}',
        26, 'player_26', 1367, 2, 28000, 28000,
        '{"card": "card.inferno", "avatar": "bean.ninja", "arena": "arena.neon", "color": "#3b82f6", "weapon": "weapon.arrows"}',
        FALSE, 2, 3, 2, '{"slots": [{"slug": "xor-pairs", "tier": 1}, {"slug": "gray-ladder", "tier": 2}, {"slug": "lone-bit", "tier": 3}, {"slug": "peak-finder", "tier": 4}]}',
        3866, 'Player_3866', 1302, 2, 28000, 28000,
        '{"card": "card.classic", "avatar": "bean.plain", "arena": null, "color": "#22c55e", "weapon": "weapon.fireball"}',
        FALSE, 2, 3, 2, '{"slots": [{"slug": "bit-count", "tier": 1}, {"slug": "mex-run", "tier": 2}, {"slug": "subset-parade", "tier": 3}, {"slug": "kth-gap", "tier": 4}]}');

-- =============================================================================
-- Q32 · READ · Reconnect or open the result page: the match and the public
-- events after the last one the browser has
-- App: api/matches.py:202 and :205-206 (the match, then its events); also
-- api/matches.py:178. Here one LEFT JOIN.
-- =============================================================================
-- READ
SELECT m.status, m.last_seq, m.result, e.seq, e.t_ms, e.type, e.payload
FROM matches m
LEFT JOIN match_events e ON e.match_id = m.id
                        AND e.seq > 10
                        AND e.visibility = 'both'
WHERE m.id = '9348a163-6e39-4f78-8557-09984d57dc04'
ORDER BY e.seq
LIMIT 500;

-- #############################################################################
-- A live match (each command is saved in one transaction, then broadcast)
-- #############################################################################

-- =============================================================================
-- Q33 · WRITE · Both players are ready: the match goes live
-- App: engine/actor.py:315 (session.merge of the match after the ready check)
-- =============================================================================
-- WRITE
UPDATE matches
SET status = 'live', start_time = now() AT TIME ZONE 'utc', last_seq = 3
WHERE id = 'b5e0c0de-1111-4222-8333-444455556666';

-- =============================================================================
-- Q34 · READ · Before each save, the ORM loads the match row it merges into
-- App: engine/actor.py:313 (session.merge issues a primary-key SELECT)
-- =============================================================================
-- READ
SELECT *
FROM matches
WHERE id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f';

-- =============================================================================
-- Q35 · WRITE · Save the match after a hit lands (HP, hand, stats, last event number)
-- App: engine/actor.py:315 (session.merge). The ORM writes only the changed
-- columns, so other commands (block, hint, reroll, connect) update a different
-- subset of the player1_*/player2_* columns; this is the largest common one.
-- =============================================================================
-- WRITE
UPDATE matches
SET last_seq = 17,
    player1_damage_dealt = 8000,
    player1_hits_landed = 1,
    player1_hand = '{"slots": [{"slug": "bit-count", "tier": 1}, {"slug": "mex-run", "tier": 2}, {"slug": "lone-bit", "tier": 3}, {"slug": "kth-gap", "tier": 4}]}',
    player1_stats = '{"crits": 0, "accepted": 1, "submissions": 1, "biggest_hit": 8000, "fastest_solve_ms": 95000}',
    player2_hp = 6000,
    player2_stats = '{"damage_taken": 8000}'
WHERE id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f';

-- =============================================================================
-- Q36 · WRITE · Append the command's events to the match log
-- App: engine/actor.py:321 (one INSERT per event, same transaction)
-- =============================================================================
-- WRITE
INSERT INTO match_events (match_id, seq, t_ms, type, payload, visibility)
VALUES ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 15, 301250, 'submission.received', '{"side": 1, "slot": 2, "submission_id": 1}', 'both'),
       ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 16, 303900, 'submission.verdict', '{"side": 1, "slot": 2, "verdict": "AC"}', 'both'),
       ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 17, 303910, 'attack.hit', '{"attacker": 1, "damage": 8000, "defender_hp": 6000}', 'both');

-- =============================================================================
-- Q37 · WRITE · A player submits a card
-- App: engine/actor.py:316 (session.merge of the new submission)
-- =============================================================================
-- WRITE
INSERT INTO submissions (match_id, profile_id, problem_id, slot, language, code, cmd_id)
VALUES ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 101, 3, 2, 'cpp',
        E'#include <bits/stdc++.h>\nusing namespace std;\nint main(){long long n;cin>>n;cout<<__builtin_popcountll(n)<<"\\n";}',
        'cmd-live-0001')
RETURNING id;

-- =============================================================================
-- Q38 · READ · Before saving the verdict, the ORM loads the submission it merges into
-- App: engine/actor.py:315 (session.merge issues a primary-key SELECT). The
-- app binds the id; here (SELECT currval(...)) stands for "the id Q37 returned".
-- It must be a subquery: a bare currval() is volatile and would make
-- PostgreSQL scan the table instead of using the primary key.
-- =============================================================================
-- READ
SELECT *
FROM submissions
WHERE id = (SELECT currval('submissions_id_seq'));

-- =============================================================================
-- Q39 · WRITE · Record the judge's verdict and the damage it did
-- App: engine/actor.py:316. Other verdicts write failed_test and recoil, or
-- blocked and crit, instead of damage.
-- =============================================================================
-- WRITE
UPDATE submissions
SET status = 'done', verdict = 'AC', tests_passed = 8, tests_total = 8, time_ms = 41,
    memory_kb = 3480, damage = 8000, crit = FALSE
WHERE id = (SELECT currval('submissions_id_seq'));

-- =============================================================================
-- Q40 · WRITE · Save the editor's draft (insert, or overwrite the same slot and language)
-- App: api/matches.py:300-308 (SELECT, then INSERT or UPDATE); here one upsert.
-- =============================================================================
-- WRITE
INSERT INTO drafts (match_id, profile_id, slot, language, code, problem_slug, updated_at)
VALUES ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 101, 3, 'python', E'n = int(input())\nprint(bin(n).count("1"))',
        'bit-count', now() AT TIME ZONE 'utc')
ON CONFLICT (match_id, profile_id, slot, language)
DO UPDATE SET code = EXCLUDED.code, problem_slug = EXCLUDED.problem_slug, updated_at = EXCLUDED.updated_at;

-- =============================================================================
-- Q41 · READ · Reopen the editor: all my drafts in this match
-- App: api/matches.py:317
-- =============================================================================
-- READ
SELECT slot, language, code, problem_slug, updated_at
FROM drafts
WHERE match_id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f'
  AND profile_id = 101;

-- =============================================================================
-- Q42 · READ · One slot's draft
-- App: api/matches.py:327
-- =============================================================================
-- READ
SELECT slot, language, code, problem_slug
FROM drafts
WHERE match_id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f'
  AND profile_id = 101
  AND slot = 3
LIMIT 1;

-- =============================================================================
-- Q43 · WRITE · A card was submitted: drop that slot's drafts
-- App: engine/actor.py:755
-- =============================================================================
-- WRITE
DELETE FROM drafts
WHERE match_id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f'
  AND profile_id = 101
  AND slot = 3;

-- =============================================================================
-- Q44 · WRITE · Flag a match for review (repeated judge system errors)
-- App: engine/actor.py:661 and :956-959 (_flag)
-- =============================================================================
-- WRITE
INSERT INTO flags (match_id, profile_id, kind, severity, details)
VALUES ('552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f', 101, 'judge_system_errors', 1, '{"count": 3}');

-- =============================================================================
-- Q45 · READ · Rebuild a match from its log (replays, recovery)
-- App: engine/actor.py:950-951 (_load_events, every visibility)
-- =============================================================================
-- READ
SELECT seq, t_ms, type, payload, visibility
FROM match_events
WHERE match_id = '9348a163-6e39-4f78-8557-09984d57dc04'
  AND seq > 0
ORDER BY seq;

-- #############################################################################
-- The end of a match (one transaction: the match, ratings, rewards, unlocks)
-- #############################################################################

-- =============================================================================
-- Q46 · WRITE · Close the match: outcome, labels, the result screen
-- App: engine/actor.py:315 (session.merge after the final command)
-- =============================================================================
-- WRITE
UPDATE matches
SET status = 'finished', end_time = now() AT TIME ZONE 'utc', elapsed_ms = 1010000,
    end_reason = 'ko', outcome = 'win', winner_side = 1,
    labels = '{"1": "victory", "2": "defeat"}',
    result = '{"outcome": "win", "end_reason": "ko", "winner_side": 1, "sides": {"1": {"before": 1250, "after": 1271, "delta": 21}, "2": {"before": 1222, "after": 1207, "delta": -15}}}',
    last_seq = 20, player2_hp = 0
WHERE id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f';

-- =============================================================================
-- Q47 · WRITE · Void submissions still being judged when the match ended
-- App: engine/actor.py:654 and :316 (one UPDATE per submission); here one UPDATE.
-- =============================================================================
-- WRITE
UPDATE submissions
SET status = 'void'
WHERE match_id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f'
  AND status = 'judging';

-- =============================================================================
-- Q48 · WRITE · Delete every draft of the match
-- App: engine/actor.py:894
-- =============================================================================
-- WRITE
DELETE FROM drafts
WHERE match_id = '552ba0bd-997e-4e6f-8bb9-dc5a3cec1f7f';

-- =============================================================================
-- Q49 · READ · Rematch rule: ranked meetings of the same pair in the last hour
-- App: engine/finish.py:46-53 (_previous_meetings; the app counts the rows)
-- =============================================================================
-- READ
SELECT count(*)
FROM matches
WHERE mode = 'ranked'
  AND status = 'finished'
  AND id <> '9348a163-6e39-4f78-8557-09984d57dc04'
  AND end_time >= timestamp '2026-11-23 11:00'
  AND ((player1_profile_id = 26 AND player2_profile_id = 3866)
    OR (player1_profile_id = 3866 AND player2_profile_id = 26));

-- =============================================================================
-- Q50 · READ · The people in the match (bots have no rating to change)
-- App: engine/finish.py:77 (one primary-key lookup per side); here one IN list.
-- =============================================================================
-- READ
SELECT id, rating, peak_rating, wins, losses, draws, points, bot_gain_today, casual_ap_today,
       daily_day, last_win_day, counters, badges
FROM profiles
WHERE id IN (26, 3866)
  AND NOT is_bot;

-- =============================================================================
-- Q51 · WRITE · Apply the result to a player: rating, peak, W/L/D, AP, daily counters
-- App: engine/finish.py:89-121 and _progress (the app computes each value and
-- writes it; the counters reset when the UTC day changes)
-- =============================================================================
-- WRITE
UPDATE profiles
SET rating = 1388,
    peak_rating = greatest(peak_rating, 1388),
    wins = wins + 1,
    points = points + 85,
    bot_gain_today = CASE WHEN daily_day = '2026-11-23' THEN bot_gain_today ELSE 0 END,
    casual_ap_today = CASE WHEN daily_day = '2026-11-23' THEN casual_ap_today ELSE 0 END,
    daily_day = '2026-11-23',
    last_win_day = '2026-11-23'
WHERE id = 26;

-- =============================================================================
-- Q52 · WRITE · Record the rating change and its breakdown
-- App: engine/finish.py:109
-- =============================================================================
-- WRITE
INSERT INTO rating_history (profile_id, match_id, before, after, delta, steps, multiplier)
VALUES (26, '9348a163-6e39-4f78-8557-09984d57dc04', 1367, 1388, 21,
        '[{"key": "base_win", "delta": 16}, {"key": "hp_left", "delta": 3}, {"key": "speed", "delta": 2}]', 100);

-- =============================================================================
-- Q53 · WRITE · Daily quest progress (create today's row or add to it)
-- App: engine/finish.py:168-176 (SELECT, then INSERT or UPDATE); here one upsert
-- that never moves a quest that is already earned.
-- =============================================================================
-- WRITE
INSERT INTO quest_progress (profile_id, day, key, progress, target)
VALUES (26, '2026-11-23', 'daily_grind', 1, 3)
ON CONFLICT (profile_id, day, key) DO UPDATE
SET progress  = least(quest_progress.target, quest_progress.progress + EXCLUDED.progress),
    earned_at = CASE WHEN quest_progress.progress + EXCLUDED.progress >= quest_progress.target
                     THEN now() AT TIME ZONE 'utc' END
WHERE quest_progress.earned_at IS NULL;

-- =============================================================================
-- Q54 · WRITE · A new achievement: record it, add the badge, save the counters
-- App: engine/finish.py:181-188 (INSERT, then the profile's badges and counters
-- in the later profile UPDATE); here one statement joined on the new row.
-- =============================================================================
-- WRITE
WITH earned AS (
    INSERT INTO achievements (profile_id, key, progress, earned_at)
    VALUES (26, 'flawless', 1, now() AT TIME ZONE 'utc')
    ON CONFLICT (profile_id, key) DO NOTHING
    RETURNING profile_id, key
)
UPDATE profiles p
SET badges = (SELECT json_agg(b ORDER BY b)
              FROM (SELECT json_array_elements_text(coalesce(p.badges, '[]')) AS b UNION SELECT e.key) t),
    counters = '{"career_blocks": 1, "bit_wins": 15, "ac_streak": 4, "ranked_win_streak": 1}'
FROM earned e
WHERE p.id = e.profile_id;

-- =============================================================================
-- Q55 · WRITE · Unlock skins the player has just earned (tier or achievement)
-- App: skins/service.py:36 (evaluate_unlocks; the app checks the owned set first)
-- =============================================================================
-- WRITE
INSERT INTO inventory (profile_id, skin_id, source)
VALUES (26, 'card.azure', 'tier'),
       (26, 'bean.cape', 'tier')
ON CONFLICT (profile_id, skin_id) DO NOTHING;

-- =============================================================================
-- Q56 · WRITE · No-show: add a strike, and ban from the queue on the third
-- App: engine/finish.py:33-40 (apply_strikes; one lookup and save per player);
-- here one UPDATE for both.
-- =============================================================================
-- WRITE
UPDATE profiles
SET no_show_strikes = CASE WHEN no_show_strikes + 1 >= 3 THEN 0 ELSE no_show_strikes + 1 END,
    queue_ban_until = CASE WHEN no_show_strikes + 1 >= 3
                           THEN (now() AT TIME ZONE 'utc') + interval '15 minutes'
                           ELSE queue_ban_until END
WHERE id IN (101, 5001);

-- #############################################################################
-- Locker and shop
-- #############################################################################

-- =============================================================================
-- Q57 · READ · Shop: was this purchase already made (a retried click)?
-- App: skins/service.py:58
-- =============================================================================
-- READ
SELECT id, skin_id, price
FROM purchases
WHERE profile_id = 26
  AND idem_key = 'b7c1e5d0-buy-arena-sakura';

-- =============================================================================
-- Q58 · WRITE · Buy a skin: take the Arena Points, add it to the inventory,
-- record the purchase
-- App: skins/service.py:59-75 (checks in Python, then an UPDATE and two
-- INSERTs); here one statement that does nothing when the player cannot pay
-- or already owns it.
-- =============================================================================
-- WRITE
WITH paid AS (
    UPDATE profiles
    SET points = points - 1800
    WHERE id = 26
      AND points >= 1800
      AND NOT EXISTS (SELECT 1 FROM inventory WHERE profile_id = 26 AND skin_id = 'arena.sakura')
    RETURNING id
), owned AS (
    INSERT INTO inventory (profile_id, skin_id, source)
    SELECT id, 'arena.sakura', 'ap'
    FROM paid
    RETURNING profile_id
)
INSERT INTO purchases (profile_id, skin_id, idem_key, price)
SELECT profile_id, 'arena.sakura', 'b7c1e5d0-buy-arena-sakura', 1800
FROM owned
RETURNING id;

-- =============================================================================
-- Q59 · WRITE · Equip a skin (card, fighter, arena or weapon)
-- App: api/skins.py:48-64
-- =============================================================================
-- WRITE
UPDATE profiles
SET equipped_arena = 'arena.sakura'
WHERE id = 26;

-- =============================================================================
-- Q60 · WRITE · Report an opponent: the target is whoever else was in the match
-- App: api/players.py:155-159 (SELECT the match, then INSERT); here INSERT ... SELECT.
-- =============================================================================
-- WRITE
INSERT INTO reports (reporter_id, match_id, target_profile_id, reason)
SELECT 26, m.id,
       CASE WHEN m.player1_profile_id = 26 THEN m.player2_profile_id ELSE m.player1_profile_id END,
       'They submitted a full solution in four seconds'
FROM matches m
WHERE m.id = '9348a163-6e39-4f78-8557-09984d57dc04';

-- #############################################################################
-- Admin
-- #############################################################################

-- =============================================================================
-- Q61 · READ · Admin: the latest 100 matches, searched by player name or id
-- App: api/admin.py:45-48 (the app filters the 100 rows in Python)
-- =============================================================================
-- READ
SELECT id, mode, map, status, created_at, end_reason, winner_side, player1_name, player2_name
FROM (SELECT *
      FROM matches
      ORDER BY created_at DESC
      LIMIT 100) recent
WHERE lower(player1_name || player2_name || id) LIKE '%player_1%'
ORDER BY created_at DESC;

-- =============================================================================
-- Q62 · READ · Admin: a match's full event log, private events included
-- App: api/admin.py:58
-- =============================================================================
-- READ
SELECT seq, t_ms, type, visibility, payload
FROM match_events
WHERE match_id = '9348a163-6e39-4f78-8557-09984d57dc04'
ORDER BY seq;

-- =============================================================================
-- Q63 · WRITE · Admin: void a match (reverse every rating change it made)
-- App: api/admin.py:73-80 (SELECT the rows, then a profile lookup and two
-- saves per row); here one UPDATE ... FROM over the rows it voids.
-- =============================================================================
-- WRITE
WITH reversed AS (
    UPDATE rating_history
    SET voided = TRUE
    WHERE match_id = '9348a163-6e39-4f78-8557-09984d57dc04'
      AND NOT voided
    RETURNING profile_id, delta
)
UPDATE profiles p
SET rating = greatest(0, p.rating - r.delta)
FROM reversed r
WHERE p.id = r.profile_id
RETURNING p.id, p.rating;

-- =============================================================================
-- Q64 · WRITE · Admin: write the audit log
-- App: api/admin.py:24 (_audit, after every admin action)
-- =============================================================================
-- WRITE
INSERT INTO audit_log (actor_id, action, target, details)
VALUES (1, 'void_match', '9348a163-6e39-4f78-8557-09984d57dc04', '{"reason": "shared account", "rows": 2}');

-- =============================================================================
-- Q65 · READ · Admin: the latest 200 flags
-- App: api/admin.py:100
-- =============================================================================
-- READ
SELECT id, match_id, profile_id, kind, severity, details, status, created_at
FROM flags
ORDER BY created_at DESC
LIMIT 200;

-- =============================================================================
-- Q66 · WRITE · Admin: resolve a flag
-- App: api/admin.py:113-117
-- =============================================================================
-- WRITE
UPDATE flags
SET status = 'dismissed'
WHERE id = 1;

-- =============================================================================
-- Q67 · WRITE · Admin: suspend a user for a week
-- App: api/admin.py:132-136 (SELECT, then UPDATE); here one UPDATE.
-- =============================================================================
-- WRITE
UPDATE users
SET suspended_until = (now() AT TIME ZONE 'utc') + interval '7 days'
WHERE username_lower = 'player_26';

-- =============================================================================
-- Q68 · WRITE · Admin: give a skin to a user by username
-- App: api/admin.py:151-156 (user, profile and owned-check lookups, then
-- INSERT); here INSERT ... SELECT over a JOIN.
-- =============================================================================
-- WRITE
INSERT INTO inventory (profile_id, skin_id, source)
SELECT p.id, 'card.glitch', 'admin'
FROM users u
JOIN profiles p ON p.user_id = u.id
WHERE u.username_lower = 'player_26'
ON CONFLICT (profile_id, skin_id) DO NOTHING;

-- =============================================================================
-- Q69 · WRITE · Admin: reset a user's daily caps
-- App: api/admin.py:166-172 (two lookups, then UPDATE); here UPDATE ... FROM.
-- =============================================================================
-- WRITE
UPDATE profiles p
SET bot_gain_today = 0, casual_ap_today = 0
FROM users u
WHERE u.id = p.user_id
  AND u.username_lower = 'player_26';

-- #############################################################################
-- The server
-- #############################################################################

-- =============================================================================
-- Q70 · READ · Health check
-- App: main.py:141 (GET /healthz)
-- =============================================================================
-- READ
SELECT 1;

-- =============================================================================
-- Q71 · WRITE · After a database error in a match: abort it
-- App: engine/actor.py:287-293
-- =============================================================================
-- WRITE
UPDATE matches
SET status = 'aborted', end_reason = 'aborted', outcome = 'aborted',
    result = '{"outcome": "aborted", "end_reason": "aborted", "reason": "server_error", "sides": {}}',
    last_seq = 15
WHERE id = '8f1f9562-bc91-4039-88fd-b5b2a78559d0';

-- =============================================================================
-- Q72 · WRITE · Start-up: abort every match the last process left running
-- App: engine/service.py:63-69 (SELECT them, then save each); here one UPDATE.
-- =============================================================================
-- WRITE
UPDATE matches
SET status = 'aborted', end_reason = 'aborted', outcome = 'aborted',
    result = '{"outcome": "aborted", "end_reason": "aborted", "reason": "server_restarted", "sides": {}}'
WHERE status IN ('starting', 'live');

-- #############################################################################
-- Seeding (make seed)
-- #############################################################################

-- =============================================================================
-- Q73 · WRITE · Seed: add or update a problem by slug
-- App: seed.py:39-62 (SELECT by slug, then INSERT or UPDATE); here one upsert.
-- =============================================================================
-- WRITE
INSERT INTO problems (slug, title, statement_md, biome, rating, tier, base_damage, base_recoil, time_limit_ms,
                      memory_mb, checker, tags, hints, stubs, status)
VALUES ('lone-bit', 'Lone Bit', 'Find the number that appears once.', 'bit', 1450, 3, 15000, 7500, 2000,
        256, 'exact', '["xor"]', '["XOR cancels pairs.", "Fold the whole array.", "x ^ x = 0"]', '{}', 'published')
ON CONFLICT (slug) DO UPDATE
SET title = EXCLUDED.title, statement_md = EXCLUDED.statement_md, rating = EXCLUDED.rating, tier = EXCLUDED.tier,
    base_damage = EXCLUDED.base_damage, base_recoil = EXCLUDED.base_recoil, hints = EXCLUDED.hints
RETURNING id;

-- =============================================================================
-- Q74 · WRITE · Seed: remove a problem's old test cases
-- App: seed.py:64
-- =============================================================================
-- WRITE
DELETE FROM test_cases
WHERE problem_id = 3;

-- =============================================================================
-- Q75 · WRITE · Seed: write its new test cases
-- App: seed.py:66
-- =============================================================================
-- WRITE
INSERT INTO test_cases (problem_id, idx, input_text, expected_text, is_sample)
VALUES (3, 0, E'5\n1 2 3 2 1\n', E'3\n', TRUE),
       (3, 1, E'1\n7\n', E'7\n', TRUE),
       (3, 2, E'7\n4 4 9 1 9 1 6\n', E'6\n', FALSE);

-- =============================================================================
-- Q76 · WRITE · Seed: create a bot profile if it does not exist
-- App: seed.py:104-110 (ensure_bots: SELECT, then INSERT)
-- =============================================================================
-- WRITE
INSERT INTO profiles (display_name, is_bot, personality, rating, peak_rating, avatar_color)
SELECT 'Turtle', TRUE, 'turtle', 1200, 1200, '#22c55e'
WHERE NOT EXISTS (SELECT 1 FROM profiles WHERE is_bot AND personality = 'turtle');

-- END
ROLLBACK;
