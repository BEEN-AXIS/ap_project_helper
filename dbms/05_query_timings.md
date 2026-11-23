# 05 · Query timings

Every one of the 76 queries in [`04_queries.sql`](04_queries.sql) was run three times on
PostgreSQL 16 against a year of generated play for 20,000 players. The tables below give
Run 1, Run 2, Run 3 and the average in milliseconds; the raw `EXPLAIN (ANALYZE, BUFFERS)`
output for every run of every query is in [`plans/`](plans/) (`plans/Q01.txt` … `plans/Q76.txt`,
plus [`plans/timings.json`](plans/timings.json) with the same numbers and the planning times).

**In short:** 67 of 76 queries average under 1 ms and 26 under 0.1 ms. 5 are slow, all
of them reads that scan a whole table: the weekly leaderboard (Q25, 141.123 ms), the
map leaderboard (Q26, 90.821 ms), the admin match list (Q61, 84.750 ms),
the all-time leaderboard (Q24, 22.632 ms) and a player's rank (Q23, 12.156 ms).
Every write a live match makes takes well under a millisecond. Six indexes the app does not
have yet bring the five slow reads down to 0.3–89 ms and the whole file from
372 ms to 151 ms (see [Indexes that would fix them](#indexes-that-would-fix-them)).

## Setup

| | |
|---|---|
| Machine | Linux container, 2 vCPU (Intel Xeon @ 2.10 GHz), 7 GB RAM |
| Database | PostgreSQL 16.15 |
| Settings changed | `shared_buffers = 512MB`, `work_mem = 16MB`, `max_wal_size = 2GB`, `synchronous_commit = off`, `jit = off`; everything else default |
| Schema | [`03_schema.sql`](03_schema.sql) as it is: only the indexes the app itself creates |
| Data | [`tools/load_problems.py`](tools/load_problems.py) (the 17 real problems, 144 test cases) and [`tools/benchmark_data.sql`](tools/benchmark_data.sql) (seeded, so every load is identical; "now" is fixed at 2026-11-23 12:00 UTC), then `VACUUM ANALYZE` |

The data is shaped like the game: some players play far more than others, 60% of matches are
ranked, 30% against bots and 10% practice, a few are drawn or aborted, 50 are being played
"now", and matches were inserted in time order, as the app writes them.

| Table | Rows | Size on disk |
|---|---:|---:|
| match_events | 2,500,520 | 804 MB |
| submissions | 499,940 | 227 MB |
| matches | 100,050 | 168 MB |
| rating_history | 145,715 | 38 MB |
| inventory | 240,862 | 35 MB |
| quest_progress | 188,680 | 28 MB |
| refresh_tokens | 60,000 | 17 MB |
| profiles | 20,005 (20,000 people, 4 bots, 1 practice dummy) | 15 MB |
| purchases | 26,401 | 5 MB |
| users | 20,000 | 5 MB |
| test_cases | 144 | 4 MB |
| achievements · audit_log · flags · reports · drafts · problems | 15,642 · 3,000 · 2,000 · 567 · 400 · 17 | 4 MB together |
| **Total** | **3.8 million rows** | **1.4 GB** |

## Method

- **What is timed.** Each statement is wrapped in `EXPLAIN (ANALYZE, BUFFERS)`, which really
  executes it and reports the plan, the rows at every step and the time. The number recorded
  is PostgreSQL's `Execution Time`: time spent running the statement on the server. Planning
  time is left out of the tables (it is in each plan file and in `timings.json`; it is under
  0.5 ms for every query, 0.05 ms typically), and so is sending rows to a client.
- **Writes really write.** Each run executes the whole of `04_queries.sql` from top to bottom
  inside one transaction and then rolls it back. Inserts, updates and deletes do their full
  work (constraint checks, foreign keys, index updates), later queries see what earlier ones
  wrote just as they do in the app (Q38 reads the submission Q37 inserted), and every run
  starts from the same data.
- **Run 1, 2, 3.** The server is restarted before Run 1, so PostgreSQL's buffer cache is
  empty and every page has to be fetched again. The operating system's file cache could not be
  cleared in this container, so those fetches come from memory, not disk: Run 1 is "cold
  PostgreSQL, warm OS". Runs 2 and 3 follow straight after with the pages already cached.
  Across all 76 queries the three runs took 369, 333 and 414 ms, so with
  the OS cache warm, a cold start costs less than the noise between runs.
- **How far to trust them.** This is a shared 2-vCPU machine, so sub-millisecond figures move
  by about ±0.1 ms between runs, and the slow queries by ±15%. `EXPLAIN ANALYZE` adds a little
  overhead of its own to plans that pass many rows between steps. The numbers are the
  database's share only: the app runs these through SQLAlchemy, and it could not be run against
  PostgreSQL here (no PostgreSQL driver could be installed), so request time in the app adds
  its own Python and network time on top.

## Results

36 reads and 40 writes. Kind is the `-- READ` / `-- WRITE` mark from `04_queries.sql`.

### Accounts and sessions

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q01 | Sign up: is the username taken? | READ | 0.096 | 0.067 | 0.087 | **0.083** | [Q01.txt](plans/Q01.txt) |
| Q02 | Sign up: create the user, their profile and their default skins | WRITE | 1.427 | 1.042 | 1.299 | **1.256** | [Q02.txt](plans/Q02.txt) |
| Q03 | Log in: the user and their profile | READ | 0.043 | 0.035 | 0.049 | **0.042** | [Q03.txt](plans/Q03.txt) |
| Q04 | The signed-in player (GET /me and every session payload): profile, account role and owned skins | READ | 0.159 | 0.119 | 0.138 | **0.139** | [Q04.txt](plans/Q04.txt) |
| Q05 | Issue a refresh token (only its SHA-256 is stored) | WRITE | 0.353 | 0.275 | 0.266 | **0.298** | [Q05.txt](plans/Q05.txt) |
| Q06 | Refresh: the token, its user and their profile | READ | 0.044 | 0.044 | 0.048 | **0.045** | [Q06.txt](plans/Q06.txt) |
| Q07 | Refresh with a token that was already used: revoke the whole family | WRITE | 0.188 | 0.146 | 0.163 | **0.166** | [Q07.txt](plans/Q07.txt) |
| Q08 | Refresh: rotate (revoke the token that was just used) | WRITE | 0.083 | 0.067 | 0.042 | **0.064** | [Q08.txt](plans/Q08.txt) |
| Q09 | Log out: revoke the cookie's token | WRITE | 0.058 | 0.051 | 0.048 | **0.052** | [Q09.txt](plans/Q09.txt) |

### Home and profile pages

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q10 | Home: my last 8 finished or aborted matches | READ | 0.718 | 0.302 | 0.366 | **0.462** | [Q10.txt](plans/Q10.txt) |
| Q11 | Home: today's quest progress | READ | 0.043 | 0.028 | 0.034 | **0.035** | [Q11.txt](plans/Q11.txt) |
| Q12 | Save settings (volumes, music, code templates) | WRITE | 0.129 | 0.102 | 0.126 | **0.119** | [Q12.txt](plans/Q12.txt) |
| Q13 | Claim a finished quest and pay its Arena Points | WRITE | 0.254 | 0.172 | 0.200 | **0.209** | [Q13.txt](plans/Q13.txt) |
| Q14 | Profile page: find the player by name (case-insensitive) | READ | 0.021 | 0.025 | 0.028 | **0.025** | [Q14.txt](plans/Q14.txt) |
| Q15 | Profile page: the last 50 rating changes (the rating chart) | READ | 0.368 | 0.092 | 0.110 | **0.190** | [Q15.txt](plans/Q15.txt) |
| Q16 | Profile page: battle history (last 20 finished or aborted) | READ | 0.227 | 0.222 | 0.232 | **0.227** | [Q16.txt](plans/Q16.txt) |
| Q17 | Profile page: accuracy (accepted out of judged) | READ | 0.759 | 0.269 | 0.359 | **0.462** | [Q17.txt](plans/Q17.txt) |
| Q18 | Career stats: up to 1000 finished matches (streaks, maps, activity) | READ | 0.233 | 0.169 | 0.284 | **0.229** | [Q18.txt](plans/Q18.txt) |
| Q19 | Career stats: submissions by language, by verdict, and in total | READ | 0.285 | 0.380 | 0.325 | **0.330** | [Q19.txt](plans/Q19.txt) |
| Q20 | Career stats: distinct problems solved, by topic and tier | READ | 0.315 | 0.276 | 0.340 | **0.310** | [Q20.txt](plans/Q20.txt) |
| Q21 | A player's achievements | READ | 0.025 | 0.015 | 0.016 | **0.019** | [Q21.txt](plans/Q21.txt) |
| Q22 | The skins a player owns | READ | 0.014 | 0.037 | 0.017 | **0.023** | [Q22.txt](plans/Q22.txt) |
| Q23 | Rank among people: how many rate higher, and how many there are | READ | 14.385 | 9.937 | 12.146 | **12.156** | [Q23.txt](plans/Q23.txt) |

### Leaderboards

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q24 | Leaderboard, all time: the top 100 by rating | READ | 20.129 | 19.343 | 28.424 | **22.632** | [Q24.txt](plans/Q24.txt) |
| Q25 | Leaderboard, this week: rating gained in matches that ended in the last 7 days | READ | 148.696 | 126.282 | 148.390 | **141.123** | [Q25.txt](plans/Q25.txt) |
| Q26 | Leaderboard for one map: most wins there | READ | 91.086 | 76.615 | 104.763 | **90.821** | [Q26.txt](plans/Q26.txt) |

### Problems

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q27 | Load the problem cache: every published problem with its tests | READ | 0.228 | 0.198 | 0.299 | **0.242** | [Q27.txt](plans/Q27.txt) |
| Q28 | Practice browser: every problem with whether I have solved it | READ | 0.318 | 0.271 | 0.386 | **0.325** | [Q28.txt](plans/Q28.txt) |

### Matchmaking and creating a match

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q29 | Matchmaking: both players of an accepted pairing | READ | 0.040 | 0.034 | 0.050 | **0.041** | [Q29.txt](plans/Q29.txt) |
| Q30 | Pick a bot opponent by personality | READ | 2.080 | 1.852 | 2.591 | **2.174** | [Q30.txt](plans/Q30.txt) |
| Q31 | Create a match: both players' snapshots, hands and the decks | WRITE | 0.551 | 0.385 | 0.497 | **0.478** | [Q31.txt](plans/Q31.txt) |
| Q32 | Reconnect or open the result page: the match and the public events after the last one the browser has | READ | 0.144 | 0.069 | 0.086 | **0.100** | [Q32.txt](plans/Q32.txt) |

### A live match (each command is saved in one transaction, then broadcast)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q33 | Both players are ready: the match goes live | WRITE | 0.268 | 0.231 | 0.315 | **0.271** | [Q33.txt](plans/Q33.txt) |
| Q34 | Before each save, the ORM loads the match row it merges into | READ | 0.040 | 0.013 | 0.018 | **0.024** | [Q34.txt](plans/Q34.txt) |
| Q35 | Save the match after a hit lands (HP, hand, stats, last event number) | WRITE | 0.166 | 0.120 | 0.218 | **0.168** | [Q35.txt](plans/Q35.txt) |
| Q36 | Append the command's events to the match log | WRITE | 0.473 | 0.365 | 0.485 | **0.441** | [Q36.txt](plans/Q36.txt) |
| Q37 | A player submits a card | WRITE | 0.489 | 0.361 | 0.518 | **0.456** | [Q37.txt](plans/Q37.txt) |
| Q38 | Before saving the verdict, the ORM loads the submission it merges into | READ | 0.026 | 0.036 | 0.036 | **0.033** | [Q38.txt](plans/Q38.txt) |
| Q39 | Record the judge's verdict and the damage it did | WRITE | 0.232 | 0.232 | 0.359 | **0.274** | [Q39.txt](plans/Q39.txt) |
| Q40 | Save the editor's draft (insert, or overwrite the same slot and language) | WRITE | 0.368 | 0.226 | 0.330 | **0.308** | [Q40.txt](plans/Q40.txt) |
| Q41 | Reopen the editor: all my drafts in this match | READ | 0.018 | 0.013 | 0.025 | **0.019** | [Q41.txt](plans/Q41.txt) |
| Q42 | One slot's draft | READ | 0.010 | 0.010 | 0.015 | **0.012** | [Q42.txt](plans/Q42.txt) |
| Q43 | A card was submitted: drop that slot's drafts | WRITE | 0.016 | 0.015 | 0.022 | **0.018** | [Q43.txt](plans/Q43.txt) |
| Q44 | Flag a match for review (repeated judge system errors) | WRITE | 0.404 | 0.237 | 0.366 | **0.336** | [Q44.txt](plans/Q44.txt) |
| Q45 | Rebuild a match from its log (replays, recovery) | READ | 0.065 | 0.037 | 0.044 | **0.049** | [Q45.txt](plans/Q45.txt) |

### The end of a match (one transaction: the match, ratings, rewards, unlocks)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q46 | Close the match: outcome, labels, the result screen | WRITE | 0.235 | 0.176 | 0.336 | **0.249** | [Q46.txt](plans/Q46.txt) |
| Q47 | Void submissions still being judged when the match ended | WRITE | 0.018 | 0.015 | 0.029 | **0.021** | [Q47.txt](plans/Q47.txt) |
| Q48 | Delete every draft of the match | WRITE | 0.030 | 0.021 | 0.034 | **0.028** | [Q48.txt](plans/Q48.txt) |
| Q49 | Rematch rule: ranked meetings of the same pair in the last hour | READ | 0.091 | 0.056 | 0.082 | **0.076** | [Q49.txt](plans/Q49.txt) |
| Q50 | The people in the match (bots have no rating to change) | READ | 0.016 | 0.015 | 0.023 | **0.018** | [Q50.txt](plans/Q50.txt) |
| Q51 | Apply the result to a player: rating, peak, W/L/D, AP, daily counters | WRITE | 0.089 | 0.083 | 0.128 | **0.100** | [Q51.txt](plans/Q51.txt) |
| Q52 | Record the rating change and its breakdown | WRITE | 0.339 | 0.213 | 0.762 | **0.438** | [Q52.txt](plans/Q52.txt) |
| Q53 | Daily quest progress (create today's row or add to it) | WRITE | 0.185 | 0.119 | 0.352 | **0.219** | [Q53.txt](plans/Q53.txt) |
| Q54 | A new achievement: record it, add the badge, save the counters | WRITE | 0.922 | 0.261 | 0.459 | **0.547** | [Q54.txt](plans/Q54.txt) |
| Q55 | Unlock skins the player has just earned (tier or achievement) | WRITE | 0.125 | 0.115 | 0.141 | **0.127** | [Q55.txt](plans/Q55.txt) |
| Q56 | No-show: add a strike, and ban from the queue on the third | WRITE | 0.118 | 0.070 | 0.123 | **0.104** | [Q56.txt](plans/Q56.txt) |

### Locker and shop

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q57 | Shop: was this purchase already made (a retried click)? | READ | 0.025 | 0.011 | 0.020 | **0.019** | [Q57.txt](plans/Q57.txt) |
| Q58 | Buy a skin: take the Arena Points, add it to the inventory, record the purchase | WRITE | 0.354 | 0.233 | 0.363 | **0.317** | [Q58.txt](plans/Q58.txt) |
| Q59 | Equip a skin (card, fighter, arena or weapon) | WRITE | 0.067 | 0.076 | 0.123 | **0.089** | [Q59.txt](plans/Q59.txt) |
| Q60 | Report an opponent: the target is whoever else was in the match | WRITE | 0.326 | 0.251 | 0.345 | **0.307** | [Q60.txt](plans/Q60.txt) |

### Admin

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q61 | Admin: the latest 100 matches, searched by player name or id | READ | 71.810 | 84.031 | 98.409 | **84.750** | [Q61.txt](plans/Q61.txt) |
| Q62 | Admin: a match's full event log, private events included | READ | 0.063 | 0.064 | 0.092 | **0.073** | [Q62.txt](plans/Q62.txt) |
| Q63 | Admin: void a match (reverse every rating change it made) | WRITE | 0.419 | 0.411 | 0.501 | **0.444** | [Q63.txt](plans/Q63.txt) |
| Q64 | Admin: write the audit log | WRITE | 0.244 | 0.188 | 0.282 | **0.238** | [Q64.txt](plans/Q64.txt) |
| Q65 | Admin: the latest 200 flags | READ | 0.561 | 0.456 | 0.678 | **0.565** | [Q65.txt](plans/Q65.txt) |
| Q66 | Admin: resolve a flag | WRITE | 0.098 | 0.073 | 0.148 | **0.106** | [Q66.txt](plans/Q66.txt) |
| Q67 | Admin: suspend a user for a week | WRITE | 0.068 | 0.072 | 0.083 | **0.074** | [Q67.txt](plans/Q67.txt) |
| Q68 | Admin: give a skin to a user by username | WRITE | 0.081 | 0.123 | 0.142 | **0.115** | [Q68.txt](plans/Q68.txt) |
| Q69 | Admin: reset a user's daily caps | WRITE | 0.057 | 0.154 | 0.080 | **0.097** | [Q69.txt](plans/Q69.txt) |

### The server

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q70 | Health check | READ | 0.003 | 0.003 | 0.003 | **0.003** | [Q70.txt](plans/Q70.txt) |
| Q71 | After a database error in a match: abort it | WRITE | 0.152 | 0.135 | 0.174 | **0.154** | [Q71.txt](plans/Q71.txt) |
| Q72 | Start-up: abort every match the last process left running | WRITE | 3.317 | 1.681 | 1.972 | **2.323** | [Q72.txt](plans/Q72.txt) |

### Seeding (make seed)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q73 | Seed: add or update a problem by slug | WRITE | 0.203 | 0.192 | 0.172 | **0.189** | [Q73.txt](plans/Q73.txt) |
| Q74 | Seed: remove a problem's old test cases | WRITE | 0.494 | 0.183 | 0.264 | **0.314** | [Q74.txt](plans/Q74.txt) |
| Q75 | Seed: write its new test cases | WRITE | 0.250 | 0.220 | 0.228 | **0.233** | [Q75.txt](plans/Q75.txt) |
| Q76 | Seed: create a bot profile if it does not exist | WRITE | 2.032 | 2.157 | 2.860 | **2.350** | [Q76.txt](plans/Q76.txt) |

## The slow ones, read from their plans

- **Q25 · Leaderboard, this week (141.123 ms).** There is no index on `matches.end_time`,
  so PostgreSQL reads all 100,050 matches to keep the 5,759 that finished in the last seven days
  (about 50 ms). The rest goes on pulling each player's rating change out of the `result` JSON
  (stored as `json`, so it is re-parsed for every match: another ~50 ms), looking up 11,518
  players and grouping them.
- **Q26 · Leaderboard for one map (90.821 ms).** Again a full read of `matches`
  (86,038 of 100,050 rows thrown away) to find the wins on one map, then a hash join to profiles
  on `CASE winner_side ...` and a sort of 8,053 winners.
- **Q61 · Admin match list (84.750 ms).** "The latest 100 matches" has no index on
  `created_at`, so PostgreSQL reads every match (in parallel) and keeps the newest 100 in a
  top-N sort.
- **Q24 · Leaderboard, all time (22.632 ms).** Reads all 20,005 profiles and sorts
  them by rating to number the top 100. (The app sorts all players in Python, which is slower
  still; the query does the ranking in the database.)
- **Q23 · A player's rank (12.156 ms).** Counts the players rated higher by reading
  every profile.
- **Q30 and Q76 · Finding a bot (2.174 and 2.350 ms).** Four bot rows hide among
  20,005 profiles with no index on `personality`, so the scan reads about 9,000 rows before it
  reaches them.
- **Q14 · Profile page by name (0.025 ms here).** Looks fast only because
  `Player_26` is on the first page of the table. The app's index is on `display_name`, but the
  lookup is on `lower(display_name)`, which that index cannot serve: a name near the end of the
  table takes about 13 ms.
- Everything else uses an index the app already has (primary keys, `ix_matches_status`,
  `ix_submissions_match_id`, `ix_match_events_match_id`, `ix_rating_history_profile_created`,
  `ix_users_username_lower`, …). The busiest path, a live match, costs 0.1–0.5 ms per write, and
  the heaviest write, sign-up (Q02: user, profile and ten starter skins in one statement), costs
  1.256 ms.

## Indexes that would fix them

These six indexes were added (with [`tools/recommended_indexes.sql`](tools/recommended_indexes.sql)),
every query was timed again three times the same way, and the indexes were dropped. Their plans
are in [`plans/with_recommended_indexes/`](plans/with_recommended_indexes/). They are not in
`03_schema.sql`, which stays a faithful copy of the schema the app creates; adding them to the
app's models would be the change. Together they take 8.8 MB.

| Query | Index that serves it | Without (ms) | With (ms) | Faster |
|---|---|---:|---:|---:|
| Q61 Admin: the latest 100 matches, searched by player name or id | `matches (created_at)` | 84.750 | 0.296 | 286× |
| Q76 Seed: create a bot profile if it does not exist | `profiles (personality) WHERE is_bot` | 2.350 | 0.021 | 112× |
| Q30 Pick a bot opponent by personality | `profiles (personality) WHERE is_bot` | 2.174 | 0.030 | 72× |
| Q24 Leaderboard, all time: the top 100 by rating | `profiles (rating DESC, lower(display_name)) WHERE NOT is_bot AND user_id IS NOT NULL` | 22.632 | 0.362 | 63× |
| Q23 Rank among people: how many rate higher, and how many there are | the same ladder index (index-only count) | 12.156 | 4.749 | 2.6× |
| Q26 Leaderboard for one map: most wins there | `matches (map) INCLUDE (winner_side, player1_profile_id, player2_profile_id) WHERE status = 'finished' AND winner_side IS NOT NULL` | 90.821 | 40.458 | 2.2× |
| Q25 Leaderboard, this week: rating gained in matches that ended in the last 7 days | `matches (end_time) WHERE status = 'finished'` | 141.123 | 88.661 | 1.6× |
| Q14 with a name near the end of the table (`Player_19998`), measured separately | `profiles (lower(display_name))` | 13.121 | 0.089 | 147× |

Averages of the three runs. Q14 was timed four times outside the main runs because the sample
player in `04_queries.sql` sits on the first page.

What changes in each plan: Q61 walks the `created_at` index backwards and stops after 100 rows.
Q24 reads the first 100 entries of the ladder index in order and never sorts (this is why
Q24 orders by `rating DESC, lower(display_name)` rather than by the computed rank: the result is
the same, and the planner can then use the index). Q23 counts from the ladder index, barely
touching the table. Q26 finds the map's wins from the covering index alone (2.5 ms instead of
60); what is left is joining and sorting about 8,000 winners. Q25 gets its 5,759 matches from
the index (3 ms instead of 50) but still parses the JSON of each one; storing each side's
rating change in its own column, or summing `rating_history` if it is made to hold every
side, would take it lower.

The cost is on writes that change indexed columns, and it is hundredths of a millisecond:

| Write | Without (ms) | With (ms) | Change |
|---|---:|---:|---:|
| Q33 Both players are ready: the match goes live | 0.271 | 0.355 | +0.084 |
| Q35 Save the match after a hit lands (HP, hand, stats, last event number) | 0.168 | 0.196 | +0.028 |
| Q46 Close the match: outcome, labels, the result screen | 0.249 | 0.304 | +0.055 |
| Q51 Apply the result to a player: rating, peak, W/L/D, AP, daily counters | 0.100 | 0.177 | +0.077 |
| Q56 No-show: add a strike, and ban from the queue on the third | 0.104 | 0.155 | +0.051 |
| Q31 Create a match: both players' snapshots, hands and the decks | 0.478 | 0.471 | -0.007 |
| Q02 Sign up: create the user, their profile and their default skins | 1.256 | 1.223 | -0.033 |

Most of these changes are inside the ±0.1 ms noise. The real ones come from updates that now
touch more indexes: Q33 and Q46 change a match's `status`, an indexed column, so PostgreSQL
writes a new entry into every index on `matches`, three more than before; Q51 changes `rating`,
which used to be a cheap in-place (HOT) update and now has to update the ladder index and,
with it, every other index on `profiles`.

## Reproduce

```sh
createdb algoarena
psql -d algoarena -f dbms/03_schema.sql
python3 dbms/tools/load_problems.py | psql -d algoarena
psql -d algoarena -f dbms/tools/benchmark_data.sql      # a few minutes
psql -d algoarena -c "VACUUM ANALYZE"
python3 dbms/tools/run_timings.py --restart "pg_ctl -D <data dir> -w restart" -d algoarena
# with the recommended indexes, into their own folder:
psql -d algoarena -f dbms/tools/recommended_indexes.sql
PLANS_DIR=dbms/plans/with_recommended_indexes python3 dbms/tools/run_timings.py -d algoarena
```

`run_timings.py` passes any arguments after `--restart` to `psql` (`-h`, `-p`, `-U`, `-d`), writes
`plans/Qnn.txt` and `plans/timings.json`, and prints the table.
