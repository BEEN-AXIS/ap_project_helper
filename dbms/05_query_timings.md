# 05 · Query timings

Every one of the 77 queries in [`04_queries.sql`](04_queries.sql) was run three times on
PostgreSQL 16 against a year of generated play for 20,000 players. The tables below give
Run 1, Run 2, Run 3 and the average in milliseconds. The raw `EXPLAIN (ANALYZE, BUFFERS)`
output for every run of every query is in [`plans/`](plans/) (`plans/Q01.txt` … `plans/Q77.txt`,
plus [`plans/timings.json`](plans/timings.json) with the same numbers and the planning times).

**In short:** 70 of 77 queries average under 1 ms and 25 under 0.1 ms. Two are still over
10 ms, the weekly leaderboard (Q25, 110.584 ms) and the map leaderboard (Q26, 44.387 ms),
because they add up every match of a week or a map; the next slowest is Q23 at 5.310 ms.
Every write a live match makes takes under 2 ms.

The first measurement found five reads that scanned whole tables. Six indexes came out of it and
are now part of the app (the models and migration `0003_query_indexes`); measured back to back,
they take the whole file from 429 ms to 187 ms. See
[What the indexes changed](#what-the-indexes-changed); the plans from before are in
[`plans/before_indexes/`](plans/before_indexes/).

## Setup

| | |
|---|---|
| Machine | Linux container, 2 vCPU (Intel Xeon @ 2.10 GHz), 7 GB RAM |
| Database | PostgreSQL 16.15 |
| Settings changed | `shared_buffers = 512MB`, `work_mem = 16MB`, `max_wal_size = 2GB`, `synchronous_commit = off`, `jit = off`; everything else default |
| Schema | [`03_schema.sql`](03_schema.sql) as it is: the indexes the app creates, the six new ones included |
| Data | [`tools/load_problems.js`](tools/load_problems.js) (the 17 real problems, 144 test cases) and [`tools/benchmark_data.sql`](tools/benchmark_data.sql) (seeded, so every load is identical; "now" is fixed at 2026-11-23 12:00 UTC), then `VACUUM ANALYZE` |

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
  0.8 ms for every query, 0.08 ms typically), and so is sending rows to a client.
- **Writes really write.** Each run executes the whole of `04_queries.sql` from top to bottom
  inside one transaction and then rolls it back. Inserts, updates and deletes do their full
  work (constraint checks, foreign keys, index updates), later queries see what earlier ones
  wrote just as they do in the app (Q38 reads the submission Q37 inserted), and every run
  starts from the same data.
- **Run 1, 2, 3.** The server is restarted before Run 1, so PostgreSQL's buffer cache is
  empty and every page has to be fetched again. The operating system's file cache could not be
  cleared in this container, so those fetches come from memory, not disk: Run 1 is "cold
  PostgreSQL, warm OS". Runs 2 and 3 follow straight after with the pages already cached.
  Across all 77 queries the three runs took 226, 173 and 161 ms.
- **Before and after.** The comparison below comes from two runs made one after the other on
  the same data: first with the six new indexes dropped (into `plans/before_indexes/`), then
  with them created again (into `plans/`), each after `VACUUM ANALYZE` and a checkpoint. The
  cost to writes was measured separately, with many repetitions (see
  [What it costs](#what-it-costs)).
- **How far to trust them.** This is a shared 2-vCPU machine, so sub-millisecond figures move
  by about ±0.1 ms between runs (more for the few writes that touch many rows), and the slow
  queries by ±15%. `EXPLAIN ANALYZE` adds a little overhead of its own to plans that pass many
  rows between steps. The numbers are the database's share only: the app runs these through
  Prisma, so a request adds its own JavaScript and network time on top. (These timings were
  taken while the server was still written in Python with SQLAlchemy; the Node.js server
  that replaced it runs the same statements, minus the two ORM reads Q34 and Q38, and its
  migration builds the same schema on PostgreSQL 16, checked by `server/test/migrations.test.js`.)

## Results

37 reads and 40 writes, with the six new indexes in place. Kind is the
`-- READ` / `-- WRITE` mark from `04_queries.sql`.

### Accounts and sessions

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q01 | Sign up: is the username taken? | READ | 0.126 | 0.242 | 0.071 | **0.146** | [Q01.txt](plans/Q01.txt) |
| Q02 | Sign up: create the user, their profile and their default skins | WRITE | 1.834 | 1.150 | 1.309 | **1.431** | [Q02.txt](plans/Q02.txt) |
| Q03 | Log in: the user and their profile | READ | 0.055 | 0.044 | 0.030 | **0.043** | [Q03.txt](plans/Q03.txt) |
| Q04 | The signed-in player (GET /me and every session payload): profile, account role and owned skins | READ | 0.180 | 0.124 | 0.129 | **0.144** | [Q04.txt](plans/Q04.txt) |
| Q05 | Issue a refresh token (only its SHA-256 is stored) | WRITE | 0.530 | 0.439 | 0.219 | **0.396** | [Q05.txt](plans/Q05.txt) |
| Q06 | Refresh: the token, its user and their profile | READ | 0.054 | 0.054 | 0.041 | **0.050** | [Q06.txt](plans/Q06.txt) |
| Q07 | Refresh with a token that was already used: revoke the whole family | WRITE | 0.268 | 0.263 | 0.250 | **0.260** | [Q07.txt](plans/Q07.txt) |
| Q08 | Refresh: rotate (revoke the token that was just used) | WRITE | 0.105 | 0.072 | 0.045 | **0.074** | [Q08.txt](plans/Q08.txt) |
| Q09 | Log out: revoke the cookie's token | WRITE | 0.068 | 0.108 | 0.035 | **0.070** | [Q09.txt](plans/Q09.txt) |

### Home and profile pages

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q10 | Home: my last 8 finished or aborted matches | READ | 0.977 | 0.318 | 0.312 | **0.536** | [Q10.txt](plans/Q10.txt) |
| Q11 | Home: today's quest progress | READ | 0.085 | 0.032 | 0.024 | **0.047** | [Q11.txt](plans/Q11.txt) |
| Q12 | Save settings (volumes, music, code templates) | WRITE | 0.278 | 0.150 | 0.133 | **0.187** | [Q12.txt](plans/Q12.txt) |
| Q13 | Claim a finished quest and pay its Arena Points | WRITE | 0.437 | 0.247 | 0.248 | **0.311** | [Q13.txt](plans/Q13.txt) |
| Q14 | Profile page: find the player by name (case-insensitive) | READ | 0.034 | 0.032 | 0.026 | **0.031** | [Q14.txt](plans/Q14.txt) |
| Q15 | Profile page: the last 50 rating changes (the rating chart) | READ | 0.556 | 0.169 | 0.100 | **0.275** | [Q15.txt](plans/Q15.txt) |
| Q16 | Profile page: battle history (last 20 finished or aborted) | READ | 0.376 | 0.195 | 0.245 | **0.272** | [Q16.txt](plans/Q16.txt) |
| Q17 | Profile page: accuracy (accepted out of judged) | READ | 1.149 | 0.342 | 0.297 | **0.596** | [Q17.txt](plans/Q17.txt) |
| Q18 | Career stats: up to 1000 finished matches (streaks, maps, activity) | READ | 0.320 | 0.216 | 0.233 | **0.256** | [Q18.txt](plans/Q18.txt) |
| Q19 | Career stats: submissions by language, by verdict, and in total | READ | 0.506 | 0.269 | 0.344 | **0.373** | [Q19.txt](plans/Q19.txt) |
| Q20 | Career stats: distinct problems solved, by topic and tier | READ | 0.464 | 0.285 | 0.259 | **0.336** | [Q20.txt](plans/Q20.txt) |
| Q21 | A player's achievements | READ | 0.039 | 0.014 | 0.016 | **0.023** | [Q21.txt](plans/Q21.txt) |
| Q22 | The skins a player owns | READ | 0.028 | 0.014 | 0.014 | **0.019** | [Q22.txt](plans/Q22.txt) |
| Q23 | Rank among people: how many rate higher, and how many there are | READ | 6.547 | 4.636 | 4.748 | **5.310** | [Q23.txt](plans/Q23.txt) |

### Leaderboards

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q24 | Leaderboard, all time: the top 100 by rating | READ | 0.916 | 0.250 | 0.246 | **0.471** | [Q24.txt](plans/Q24.txt) |
| Q25 | Leaderboard, this week: rating gained in matches that ended in the last 7 days | READ | 136.385 | 98.388 | 96.980 | **110.584** | [Q25.txt](plans/Q25.txt) |
| Q26 | Leaderboard for one map: most wins there | READ | 48.989 | 46.776 | 37.397 | **44.387** | [Q26.txt](plans/Q26.txt) |
| Q77 | Leaderboard, all time: my place when I am outside the top 100 | READ | 5.225 | 5.098 | 3.907 | **4.743** | [Q77.txt](plans/Q77.txt) |

### Problems

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q27 | Load the problem cache: every published problem with its tests | READ | 0.350 | 0.307 | 0.254 | **0.304** | [Q27.txt](plans/Q27.txt) |
| Q28 | Practice browser: every problem with whether I have solved it | READ | 0.405 | 0.419 | 0.337 | **0.387** | [Q28.txt](plans/Q28.txt) |

### Matchmaking and creating a match

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q29 | Matchmaking: both players of an accepted pairing | READ | 0.087 | 0.047 | 0.035 | **0.056** | [Q29.txt](plans/Q29.txt) |
| Q30 | Pick a bot opponent by personality | READ | 0.055 | 0.022 | 0.014 | **0.030** | [Q30.txt](plans/Q30.txt) |
| Q31 | Create a match: both players' snapshots, hands and the decks | WRITE | 0.786 | 0.637 | 0.539 | **0.654** | [Q31.txt](plans/Q31.txt) |
| Q32 | Reconnect or open the result page: the match and the public events after the last one the browser has | READ | 0.177 | 0.147 | 0.101 | **0.142** | [Q32.txt](plans/Q32.txt) |

### A live match (each command is saved in one transaction, then broadcast)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q33 | Both players are ready: the match goes live | WRITE | 0.500 | 0.389 | 0.327 | **0.405** | [Q33.txt](plans/Q33.txt) |
| Q34 | Before each save, the ORM loads the match row it merges into | READ | 0.037 | 0.036 | 0.029 | **0.034** | [Q34.txt](plans/Q34.txt) |
| Q35 | Save the match after a hit lands (HP, hand, stats, last event number) | WRITE | 0.289 | 0.198 | 0.146 | **0.211** | [Q35.txt](plans/Q35.txt) |
| Q36 | Append the command's events to the match log | WRITE | 3.529 | 1.148 | 0.665 | **1.781** | [Q36.txt](plans/Q36.txt) |
| Q37 | A player submits a card | WRITE | 0.827 | 0.545 | 0.404 | **0.592** | [Q37.txt](plans/Q37.txt) |
| Q38 | Before saving the verdict, the ORM loads the submission it merges into | READ | 0.043 | 0.039 | 0.028 | **0.037** | [Q38.txt](plans/Q38.txt) |
| Q39 | Record the judge's verdict and the damage it did | WRITE | 0.358 | 0.362 | 0.242 | **0.321** | [Q39.txt](plans/Q39.txt) |
| Q40 | Save the editor's draft (insert, or overwrite the same slot and language) | WRITE | 0.547 | 0.371 | 0.352 | **0.423** | [Q40.txt](plans/Q40.txt) |
| Q41 | Reopen the editor: all my drafts in this match | READ | 0.029 | 0.024 | 0.024 | **0.026** | [Q41.txt](plans/Q41.txt) |
| Q42 | One slot's draft | READ | 0.019 | 0.013 | 0.018 | **0.017** | [Q42.txt](plans/Q42.txt) |
| Q43 | A card was submitted: drop that slot's drafts | WRITE | 0.026 | 0.021 | 0.034 | **0.027** | [Q43.txt](plans/Q43.txt) |
| Q44 | Flag a match for review (repeated judge system errors) | WRITE | 0.542 | 0.398 | 0.378 | **0.439** | [Q44.txt](plans/Q44.txt) |
| Q45 | Rebuild a match from its log (replays, recovery) | READ | 0.128 | 0.061 | 0.055 | **0.081** | [Q45.txt](plans/Q45.txt) |

### The end of a match (one transaction: the match, ratings, rewards, unlocks)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q46 | Close the match: outcome, labels, the result screen | WRITE | 0.428 | 0.306 | 0.310 | **0.348** | [Q46.txt](plans/Q46.txt) |
| Q47 | Void submissions still being judged when the match ended | WRITE | 0.028 | 0.023 | 0.052 | **0.034** | [Q47.txt](plans/Q47.txt) |
| Q48 | Delete every draft of the match | WRITE | 0.050 | 0.040 | 0.069 | **0.053** | [Q48.txt](plans/Q48.txt) |
| Q49 | Rematch rule: ranked meetings of the same pair in the last hour | READ | 0.123 | 0.116 | 0.100 | **0.113** | [Q49.txt](plans/Q49.txt) |
| Q50 | The people in the match (bots have no rating to change) | READ | 0.027 | 0.028 | 0.024 | **0.026** | [Q50.txt](plans/Q50.txt) |
| Q51 | Apply the result to a player: rating, peak, W/L/D, AP, daily counters | WRITE | 0.213 | 0.223 | 0.164 | **0.200** | [Q51.txt](plans/Q51.txt) |
| Q52 | Record the rating change and its breakdown | WRITE | 0.630 | 0.435 | 0.311 | **0.459** | [Q52.txt](plans/Q52.txt) |
| Q53 | Daily quest progress (create today's row or add to it) | WRITE | 0.338 | 0.290 | 0.146 | **0.258** | [Q53.txt](plans/Q53.txt) |
| Q54 | A new achievement: record it, add the badge, save the counters | WRITE | 0.623 | 0.611 | 0.399 | **0.544** | [Q54.txt](plans/Q54.txt) |
| Q55 | Unlock skins the player has just earned (tier or achievement) | WRITE | 0.215 | 0.135 | 0.120 | **0.157** | [Q55.txt](plans/Q55.txt) |
| Q56 | No-show: add a strike, and ban from the queue on the third | WRITE | 0.298 | 0.180 | 0.166 | **0.215** | [Q56.txt](plans/Q56.txt) |

### Locker and shop

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q57 | Shop: was this purchase already made (a retried click)? | READ | 0.040 | 0.018 | 0.014 | **0.024** | [Q57.txt](plans/Q57.txt) |
| Q58 | Buy a skin: take the Arena Points, add it to the inventory, record the purchase | WRITE | 0.535 | 0.472 | 0.343 | **0.450** | [Q58.txt](plans/Q58.txt) |
| Q59 | Equip a skin (card, fighter, arena or weapon) | WRITE | 0.127 | 0.115 | 0.107 | **0.116** | [Q59.txt](plans/Q59.txt) |
| Q60 | Report an opponent: the target is whoever else was in the match | WRITE | 0.597 | 0.511 | 0.310 | **0.473** | [Q60.txt](plans/Q60.txt) |

### Admin

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q61 | Admin: the latest 100 matches, searched by player name or id | READ | 0.479 | 0.308 | 0.211 | **0.333** | [Q61.txt](plans/Q61.txt) |
| Q62 | Admin: a match's full event log, private events included | READ | 0.065 | 0.071 | 0.055 | **0.064** | [Q62.txt](plans/Q62.txt) |
| Q63 | Admin: void a match (reverse every rating change it made) | WRITE | 0.612 | 0.548 | 0.445 | **0.535** | [Q63.txt](plans/Q63.txt) |
| Q64 | Admin: write the audit log | WRITE | 0.310 | 0.232 | 0.167 | **0.236** | [Q64.txt](plans/Q64.txt) |
| Q65 | Admin: the latest 200 flags | READ | 0.734 | 0.657 | 0.454 | **0.615** | [Q65.txt](plans/Q65.txt) |
| Q66 | Admin: resolve a flag | WRITE | 0.147 | 0.108 | 0.081 | **0.112** | [Q66.txt](plans/Q66.txt) |
| Q67 | Admin: suspend a user for a week | WRITE | 0.104 | 0.098 | 0.092 | **0.098** | [Q67.txt](plans/Q67.txt) |
| Q68 | Admin: give a skin to a user by username | WRITE | 0.109 | 0.120 | 0.114 | **0.114** | [Q68.txt](plans/Q68.txt) |
| Q69 | Admin: reset a user's daily caps | WRITE | 0.086 | 0.103 | 0.072 | **0.087** | [Q69.txt](plans/Q69.txt) |

### The server

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q70 | Health check | READ | 0.005 | 0.017 | 0.003 | **0.008** | [Q70.txt](plans/Q70.txt) |
| Q71 | After a database error in a match: abort it | WRITE | 0.263 | 0.249 | 0.161 | **0.224** | [Q71.txt](plans/Q71.txt) |
| Q72 | Start-up: abort every match the last process left running | WRITE | 2.329 | 1.447 | 4.430 | **2.735** | [Q72.txt](plans/Q72.txt) |

### Seeding (make seed)

| # | Query | Kind | Run 1 | Run 2 | Run 3 | Average (ms) | Plan |
|---|---|---|---:|---:|---:|---:|---|
| Q73 | Seed: add or update a problem by slug | WRITE | 0.246 | 0.145 | 0.160 | **0.184** | [Q73.txt](plans/Q73.txt) |
| Q74 | Seed: remove a problem's old test cases | WRITE | 0.723 | 0.217 | 0.220 | **0.387** | [Q74.txt](plans/Q74.txt) |
| Q75 | Seed: write its new test cases | WRITE | 0.437 | 0.199 | 0.183 | **0.273** | [Q75.txt](plans/Q75.txt) |
| Q76 | Seed: create a bot profile if it does not exist | WRITE | 0.035 | 0.023 | 0.026 | **0.028** | [Q76.txt](plans/Q76.txt) |

## What the indexes changed

### Before: five reads scanned whole tables

- **Q25 · Leaderboard, this week (152.768 ms).** No index on `matches.end_time`, so PostgreSQL
  read all 100,050 matches to keep the 5,759 that finished in the last seven days (about 50 ms).
  The rest went on pulling each player's rating change out of the `result` JSON (stored as
  `json`, so it is re-parsed for every match: another ~50 ms), looking up the players and
  grouping them.
- **Q26 · Leaderboard for one map (105.026 ms).** A full read of `matches` (86,038 of 100,050
  rows thrown away) to find the wins on one map, then a hash join to profiles on
  `CASE winner_side ...` and a sort of 8,053 winners.
- **Q61 · Admin match list (95.683 ms).** "The latest 100 matches" had no index on
  `created_at`, so PostgreSQL read every match (in parallel) and kept the newest 100 in a
  top-N sort.
- **Q24 · Leaderboard, all time (30.061 ms).** Read all 20,005 profiles and sorted them by
  rating to number the top 100. The app did worse at the time: it loaded every person into
  memory and sorted there.
- **Q23 · A player's rank (14.931 ms).** Counted the players rated higher by reading every
  profile.
- Smaller ones: **Q30 and Q76**, finding one of four bots, read about 9,000 profiles to reach it
  (3.006 and 2.506 ms); **Q14**, the profile page by name, used no index because the app's index
  is on `display_name` and the lookup is on `lower(display_name)`. It looked fast in the run
  (0.161 ms) only because the sample player sits on the first page; a name near the end of
  the table took about 13 ms.

### After

| Query | Index | Before (ms) | After (ms) | Faster |
|---|---|---:|---:|---:|
| Q61 Admin: the latest 100 matches, searched by player name or id | `ix_matches_created_at` | 95.683 | 0.333 | 287× |
| Q76 Seed: create a bot profile if it does not exist | `ix_profiles_bot_personality` | 2.506 | 0.028 | 89× |
| Q30 Pick a bot opponent by personality | `ix_profiles_bot_personality` | 3.006 | 0.030 | 100× |
| Q24 Leaderboard, all time: the top 100 by rating | `ix_profiles_ladder` | 30.061 | 0.471 | 64× |
| Q23 Rank among people: how many rate higher, and how many there are | `ix_profiles_ladder` | 14.931 | 5.310 | 2.8× |
| Q26 Leaderboard for one map: most wins there | `ix_matches_map_winners` | 105.026 | 44.387 | 2.4× |
| Q25 Leaderboard, this week: rating gained in matches that ended in the last 7 days | `ix_matches_finished_end_time` | 152.768 | 110.584 | 1.4× |
| Q77 Leaderboard, all time: my place when I am outside the top 100 | `ix_profiles_ladder` | 6.243 | 4.743 | 1.3× |
| Q14 with a name near the end of the table (`Player_19998`), timed separately | `ix_profiles_display_name_lower` | 13.121 | 0.089 | 147× |

Averages of the three runs, before and after. Q77, the player's own place on the all-time board,
is new (see below). Q14's worst case was timed four times outside the main runs.

What changes in each plan: Q61 walks `ix_matches_created_at` backwards and stops after 100
rows. Q24 reads the first 100 entries of `ix_profiles_ladder` in order and never sorts (this is
why Q24 orders by `rating DESC, lower(display_name)` rather than by the computed rank: the
result is the same, and the planner can then use the index). Q23 counts from the same index,
barely touching the table. Q26 finds the map's wins from the covering index alone (about 2 ms
instead of 57); what is left is joining and sorting about 8,000 winners. Q25 gets its 5,759
matches from the index (about 4 ms instead of 50) but still parses the JSON of each one. Q30,
Q76 and Q14 go straight to their row.

The indexes are partial where the app always filters the same way (people only, bots only,
finished matches only), so they stay small: 8.8 MB together. Their `WHERE` clauses repeat the
app's filters word for word, which is how PostgreSQL proves a query is covered; this was
checked with the app's own queries.

**The app's queries were changed to match.** An index does nothing for a query that does not
ask for what it holds, so the leaderboard code (now `server/src/api/players.js` and
`server/src/db/sql.js`) changed with it:

- The all-time board asks for the top 100 in index order (`ORDER BY rating DESC,
  lower(display_name) LIMIT 100`) instead of loading every player into memory.
- A player outside the top 100 gets their place from one count (Q77: the people rated higher,
  or rated the same with a name that sorts first), which the old code read off its full list.
- The weekly and map boards read three columns of the matches they need instead of whole rows,
  and the map board asks for `winner_side IS NOT NULL`, the filter its index is built on.

A test (`the leaderboards rank like before` in `server/test/api.test.js`) builds each board both
ways, the old way in memory and the new way through the indexes, and checks that the rows, scores,
ranks and the player's own place are identical.

### What it costs

Each insert into `profiles` or `matches`, and each update that changes an indexed column,
now also writes to the new indexes. The three runs of the whole file are too noisy for costs
this small, so [`tools/write_cost.js`](tools/write_cost.js) timed each of these writes 300 times
(each in its own rolled-back transaction) in three rounds: with the indexes, without them,
and with them again. Medians, from [`plans/write_cost.json`](plans/write_cost.json):

| Write | Without (ms) | With (ms) | With, again (ms) | Change |
|---|---:|---:|---:|---:|
| Q02 Sign up: create the user, their profile and their default skins | 0.269 | 0.354 | 0.384 | +0.100 |
| Q31 Create a match: both players' snapshots, hands and the decks | 0.158 | 0.203 | 0.221 | +0.054 |
| Q33 Both players are ready: the match goes live | 0.172 | 0.202 | 0.247 | +0.053 |
| Q35 Save the match after a hit lands (HP, hand, stats, last event number) | 0.130 | 0.175 | 0.196 | +0.055 |
| Q46 Close the match: outcome, labels, the result screen | 0.124 | 0.185 | 0.220 | +0.079 |
| Q51 Apply the result to a player: rating, peak, W/L/D, AP, daily counters | 0.062 | 0.106 | 0.119 | +0.050 |
| Q72 Start-up: abort every match the last process left running | 1.515 | 2.003 | 2.041 | +0.507 |
| Q36 Append the command's events to the match log | 0.098 | 0.137 | 0.146 | +0.044 |

Change is the average of the two "with" rounds minus "without". Q36 (appending match events)
touches none of the new indexes, yet moved by +0.044 ms between rounds: that is how much the
machine drifted. Against that, the indexes cost a few hundredths of a millisecond per write.
The clearest cost is Q72, which aborts 49 matches in one statement: +0.51 ms, about
0.010 ms per match, because changing a match's `status` gives the row new entries in
every index on `matches`. For comparison, the leaderboards and the admin list each save tens of
milliseconds per read.

## What is still slow

- **Q25 · weekly leaderboard (110.584 ms).** The index finds the week's matches in about 4 ms;
  the rest is reading each side's rating change out of the `result` JSON and adding them up. The
  app sums in JavaScript, and caches each board for 30 seconds, so it pays this at most twice a
  minute. To go further, store each side's rating change in its own column (or make
  `rating_history` hold every side and sum that), so the database adds numbers instead of
  parsing documents.
- **Q26 · map leaderboard (44.387 ms).** The wins come from the index in about 2 ms; joining
  them to 8,000 winners' profiles and ranking them is the rest. It is cached the same way.

## Reproduce

```sh
createdb algoarena
psql -d algoarena -f dbms/03_schema.sql
node dbms/tools/load_problems.js | psql -d algoarena
psql -d algoarena -f dbms/tools/benchmark_data.sql      # a few minutes
psql -d algoarena -c "VACUUM ANALYZE"
node dbms/tools/run_timings.js --restart "pg_ctl -D <data dir> -w restart" -d algoarena
# the "before" run: drop the six new indexes and write the plans to their own folder
psql -d algoarena -c "DROP INDEX ix_profiles_ladder, ix_profiles_display_name_lower, ix_profiles_bot_personality,
                      ix_matches_created_at, ix_matches_finished_end_time, ix_matches_map_winners"
PLANS_DIR=dbms/plans/before_indexes node dbms/tools/run_timings.js --restart "..." -d algoarena
```

`run_timings.js` passes any arguments after `--restart` to `psql` (`-h`, `-p`, `-U`, `-d`), writes
`plans/Qnn.txt` and `plans/timings.json`, and prints the table.
