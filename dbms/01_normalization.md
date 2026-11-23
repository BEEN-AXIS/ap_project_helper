# 01 · Normalization

This walks AlgoArena's data from one unnormalized "battle record" through 1NF, 2NF, 3NF
and BCNF, then checks each of the 17 tables in [`03_schema.sql`](03_schema.sql) against
those forms. The schema is the one the app really uses (the SQLModel models in
`backend/app/models/__init__.py`). Most of it reaches BCNF. Where it doesn't, the gap is a
deliberate copy of a value that could be derived, and this file names each one, gives its
BCNF form, and says why the app keeps the copy.

Notation: `R(a, b, c)` is a relation, keys are in **bold**, and `X → Y` means "X determines
Y" (a functional dependency, FD).

## 0. The data, unnormalized

Picture the game as one record per battle, with everything about it nested inside. A single
ranked match (the values are illustrative) looks like this:

```
BATTLE  b5e0c0de-…  ranked · map bit · finished · side 1 wins by KO · ended 2026-11-21 01:47
  players:
    side 1  ada  (login "Ada", password hash, role player)  rating 1367 → tier 2 → max HP 28,000
            owns: card.classic, bean.plain, weapon.fireball, arena.sakura (bought for 1,800 AP)
            refresh tokens: 3 · today's quests: first_blood 1/1, sparring 0/1 · badges: comeback
    side 2  lin  (login "Lin", …)                             rating 1235 → tier 2 → max HP 28,000
            owns: card.classic, bean.plain, weapon.fireball …
  cards dealt and submissions:
    ada  slot 0  two-singles  (rated 1500 → tier 3 → damage 15,000 / recoil 7,500)  cpp     WA
         test cases: #0 sample "3\n1 2 3" → "6", #1 …, #2 …
    lin  slot 3  split-capacity (1300 → tier 2 → 8,000 / 4,000)                        python  OLE
    ada  slot 2  range-and    (1500 → tier 3 → 15,000 / 7,500)                         python  AC  15,900 damage
  events:   1 match.created · 2 ready.check · 3 player.ready · … · 31 match.ended
  drafts:   ada slot 1 python "def solve(): …" (for card balanced-bits)
  ratings:  ada 1367 → 1379 (+12) · lin 1235 → 1218 (−17)
```

Problems with keeping it like that:

- **Repeating groups and multi-valued cells.** Players, submissions, test cases, events,
  drafts, owned skins, tokens and quests are lists inside one row.
- **Update anomalies.** A problem's title, rating, tier and test cases are repeated in every
  battle that dealt it; fixing a test case means rewriting every battle that contains it.
  A player's password hash is repeated in every battle they played.
- **Insertion anomalies.** A new player who has not played yet, or a new problem nobody has
  been dealt, has nowhere to live.
- **Deletion anomalies.** Deleting the only battle a problem appeared in deletes the problem.

## 1. First normal form

1NF asks for one value per cell, no repeating groups, and a key for every row. Each
repeating group becomes its own relation, carrying the key of the thing it belonged to:

| Relation | Key | Came from |
|---|---|---|
| users(id, username, username_lower, password_hash, role, suspended_until, created_at) | **id**; also **username_lower** | the login inside each player |
| refresh_tokens(id, user_id, token_hash, expires_at, revoked_at, created_at) | **id**; also **token_hash** | tokens, a list per user |
| profiles(id, user_id, display_name, rating, peak_rating, wins, losses, draws, points, equipped_*, settings, is_bot, personality, daily counters, counters, badges, created_at) | **id** | the player; bots are profiles without a user |
| problems(id, slug, title, statement…, biome, rating, tier, base_damage, base_recoil, limits, checker, tags, hints, stubs, …) | **id**; also **slug** | each dealt card |
| test_cases(problem_id, idx, input_text, expected_text, is_sample) | **(problem_id, idx)** | test cases, a list per problem |
| matches(id, mode, map, status, seed, times, end_reason, outcome, winner_side, labels, result, decks, last_seq, …) | **id** | the battle itself |
| match players (side 1, side 2): profile, snapshot of name and rating, tier, max HP, HP, hand, power-up charges, stats | **(match_id, side)** | players, a list of two per battle |
| submissions(id, match_id, profile_id, problem_id, slot, language, code, cmd_id, verdict, …, is_bot) | **id**; also **(profile_id, cmd_id)** | submissions, a list per battle |
| match_events(match_id, seq, t_ms, type, payload, visibility) | **(match_id, seq)** | events, a list per battle |
| drafts(match_id, profile_id, slot, language, code, problem_slug, updated_at) | **(match_id, profile_id, slot, language)** | drafts, a list per battle |
| rating_history(profile_id, match_id, before, after, delta, steps, multiplier, voided, created_at) | **(profile_id, match_id)** | rating changes, two per ranked battle |
| inventory(profile_id, skin_id, acquired_at, source) | **(profile_id, skin_id)** | owned skins, a list per player |
| purchases(profile_id, idem_key, skin_id, price, created_at) | **(profile_id, idem_key)** | the AP purchases among them |
| quest_progress(profile_id, day, key, progress, target, earned_at, claimed_at) | **(profile_id, day, key)** | quests, a list per player per day |
| achievements(profile_id, key, progress, earned_at, claimed_at) | **(profile_id, key)** | achievements, a list per player |
| flags, reports, audit_log | **id** | moderation records, each its own fact |

The built schema gives every table a surrogate `id SERIAL` primary key and declares the
natural keys above as UNIQUE constraints (`uq_test_cases_problem_idx`,
`uq_match_events_match_seq`, `uq_drafts_key`, …). Normalization is judged against **all**
candidate keys, so a surrogate `id` does not hide a dependency on part of a natural key.

Two places where the built schema stops short of strict 1NF, on purpose:

1. **The two players of a match are columns, not rows.** `matches` holds `player1_*` and
   `player2_*` (18 columns each plus the profile ids), a repeating group laid out
   sideways. The strict form is `match_players(`**match_id, side**`, profile_id, …)` with a
   second key **(match_id, profile_id)**. The app keeps the columns because a match always
   has exactly two sides and the live engine saves both after every hit in a single-row
   update (Q35, 0.17 ms).
2. **JSON columns.** PostgreSQL treats `json` as one value, and the app reads and writes
   each of these whole, so as stored they are single values: a player's `settings`,
   career `counters`, a match's `decks`, `labels` and `result`, each side's `hand`, `stats`,
   `skins` and `hints_revealed`, an event's `payload`, a rating change's `steps`, a flag's
   or audit entry's `details`. Four of them are really lists of facts, and their strict 1NF
   forms are relations of their own: `problems.tags` → `problem_tags(`**problem_id, tag**`)`,
   `problems.hints` → `problem_hints(`**problem_id, n**`, text)`, `problems.stubs` →
   `problem_stubs(`**problem_id, language**`, code)`, and `profiles.badges`, which is the list
   of achievement keys already held as rows in `achievements` (see section 3). One query
   does reach inside a document, the weekly leaderboard (Q25 reads
   `result → sides → n → delta`), and its timing in 05 is the cost of that.

## 2. Second normal form

2NF: no non-key attribute depends on only **part** of a composite candidate key. Only
relations with a composite key can fail it. Checking each one:

| Relation | Composite key | Partial dependency? |
|---|---|---|
| test_cases | (problem_id, idx) | No: input, expected output and is_sample need both. |
| match_events | (match_id, seq) | No. |
| inventory | (profile_id, skin_id) | No: acquired_at and source describe that player's copy. |
| purchases | (profile_id, idem_key) | No. |
| achievements | (profile_id, key) | No. |
| rating_history | (profile_id, match_id) | No (but see 3NF). |
| match_players | (match_id, side) | No (but see 3NF). |
| **submissions** | (profile_id, cmd_id) | **Yes: profile_id → is_bot.** Only bots send "simulated" submissions (`engine/bots.py:89`), so the flag is the submitter's `profiles.is_bot`. |
| **quest_progress** | (profile_id, day, key) | **Yes: key → target.** The target comes from the quest's definition, the same for everyone on every day (`engine/finish.py:171` copies `q.target` from `shared/game-config.json`). |
| **drafts** | (match_id, profile_id, slot, language) | **Yes: (match_id, profile_id, slot) → problem_slug.** Every draft for a slot is for the card in that slot; when the card leaves the slot (submitted or rerolled) its drafts are deleted (`engine/actor.py:752-755`, called at `:721` and `:822`). |

The 2NF decompositions:

- `submissions` loses `is_bot`; it is `profiles.is_bot` through `profile_id`.
- `quest_progress` loses `target`; a `quests(`**key**`, kind, target, ap)` relation holds it.
  That relation already exists, as the `quests` list in `shared/game-config.json`.
- `drafts` splits into `draft_slots(`**match_id, profile_id, slot**`, problem_slug)` and
  `drafts(`**match_id, profile_id, slot, language**`, code, updated_at)`.

## 3. Third normal form

3NF: no non-key attribute depends on another non-key attribute (no transitive dependency
`key → X → Y`). After 2NF these remain:

| Relation | Transitive dependency | Where the app does it |
|---|---|---|
| problems | id → rating → tier → (base_damage, base_recoil) | `seed.py:37-42`: `tier = get_tier(rating)`, then the tier's row of `tiers` in the game config |
| matches, per side | (match_id, side) → rating → tier → max_hp | `engine/service.py:97-110` (`_snapshot`) |
| matches, per side | (match_id, side) → profile_id → is_bot, and → name | the snapshot copies them; display names are written only at sign-up and never changed (`api/auth.py:82`, `seed.py`) |
| matches | id → (status, winner_side) → outcome | `engine/actor.py:897-922`: aborted ⇒ outcome *aborted*; finished with a winner ⇒ *win*; finished without ⇒ *draw* |
| rating_history | (profile_id, match_id) → (before, after) → delta | `delta = after − before`, also a CHECK (`ck_rating_history_delta`) |

The 3NF decompositions:

- A `tiers(`**tier**`, min_rating, max_hp, base_damage, base_recoil)` relation (it is the
  `tiers` list in `shared/game-config.json`). `problems` keeps `rating` and drops `tier`,
  `base_damage` and `base_recoil`. `match_players` keeps `rating` and drops `tier` and
  `max_hp`.
- `match_players` drops `name` and `is_bot` (join `profiles`).
- `matches` drops `outcome` (compute it from `status` and `winner_side`).
- `rating_history` drops `delta`.

`users` is a near miss worth spelling out: `username → username_lower` (it is
`lower(username)`), but that is **not** a 3NF or BCNF violation. Because `username_lower` is
a key and `username` determines it, `username` is a superkey too. The column is redundant
(a unique index on `lower(username)` would do the same job), not badly normalized.

### Copies across tables

Normal forms look inside one relation at a time. These copies span tables; none breaks a
normal form, but each is a value that could be computed instead of stored:

| Stored value | Could be computed from |
|---|---|
| `profiles.wins`, `losses`, `draws` | each side's label in that player's finished matches |
| `profiles.peak_rating` | `max(after)` over the player's `rating_history` |
| `profiles.badges` | the keys in the player's `achievements` rows (`engine/finish.py:184-187` writes both) |
| `profiles.display_name` of a person | `users.username` (copied at sign-up) |
| `matches.last_seq` | `max(seq)` of the match's `match_events` |
| `matches.result` (the result screen) | outcome, winner, labels and final HP of the match, and each side's rating change, which is also in `rating_history` |
| a `purchases` row | always paired with an `inventory` row whose source is `ap` |

## 4. Boyce–Codd normal form

BCNF: for every non-trivial FD `X → Y`, X is a superkey. It differs from 3NF only when an
attribute that is part of one key depends on something that is not a key, which happens
with overlapping composite keys. The one place this design has overlapping keys is
`match_players`: **(match_id, side)** and **(match_id, profile_id)** (a profile plays at
most one side of a match, `ck_matches_two_people`). The FDs between them,
`(match_id, side) → profile_id` and `(match_id, profile_id) → side`, both have a key on
the left, so it is in BCNF. Every other relation's determinants are its keys once the
section 2 and 3 changes are made, so **the decomposed design is in BCNF throughout**.

## 5. The 17 tables as built

| Table | Candidate keys | Highest form as built | What stops the next form | BCNF form |
|---|---|---|---|---|
| users | id · username_lower · username | **BCNF** | — | (could use an index on `lower(username)` instead of the column) |
| refresh_tokens | id · token_hash | **BCNF** | — | — |
| profiles | id (user_id is unique where present) | **BCNF**\* | `is_bot` is derivable from `user_id IS NULL` (held in step by `ck_profiles_kind`); `badges` is a list (1NF note) | drop `is_bot`; `badges` → `achievements` |
| problems | id · slug | **2NF** | rating → tier → base_damage, base_recoil | `tiers`; `tags`, `hints`, `stubs` as their own relations for strict 1NF |
| test_cases | id · (problem_id, idx) | **BCNF** | — | — |
| matches | id | **2NF** (and the sides are a repeating group) | rating → tier → max_hp per side; profile → name, is_bot; (status, winner_side) → outcome | `matches` + `match_players` (+ `tiers`) |
| submissions | id · (profile_id, cmd_id) | **1NF** | profile_id → is_bot, a dependency on part of a key | drop `is_bot` |
| match_events | id · (match_id, seq) | **BCNF** | — | — |
| drafts | id · (match_id, profile_id, slot, language) | **1NF** | (match_id, profile_id, slot) → problem_slug | `draft_slots` + `drafts` |
| rating_history | id · (profile_id, match_id) | **2NF** | (before, after) → delta | drop `delta` |
| quest_progress | id · (profile_id, day, key) | **1NF** | key → target | `quests` (the game config) |
| achievements | id · (profile_id, key) | **BCNF** | — | — |
| inventory | id · (profile_id, skin_id) | **BCNF** | — | — |
| purchases | id · (profile_id, idem_key) | **BCNF** | — | — |
| flags | id | **BCNF** | — | — |
| reports | id | **BCNF** | — | — |
| audit_log | id | **BCNF** | — | (`target` names any kind of object as text, so it cannot be a foreign key) |

11 of 17 tables are in BCNF as built. The other six fall short only by the derived columns
listed above.

\* If NULL is read as "no user", `profiles` is in BCNF. If NULL is treated as an ordinary
value, `user_id → is_bot` holds (NULL means a bot) while four bots share that NULL, so
`user_id` is not a key there and `is_bot` is one more derived column, guarded by
`ck_profiles_kind`.

One key the app relies on is not declared: the app writes one `rating_history` row per
player per match (`engine/finish.py:109`), so **(profile_id, match_id)** is a candidate key
in practice; `UNIQUE (profile_id, match_id)` would let the database enforce it. The
benchmark data has no duplicates.

## 6. Why the built schema keeps its copies

- **Snapshots are history, not duplicates.** A match records the name, rating, tier and
  max HP each side had *when it was played*. A player's rating moves on, and the tier table
  in the game config can be retuned; the stored tier and max HP are the ones that match was
  fought with. Strictly, the FD `rating → tier` only holds for rows written under the same
  config, which is the reason to store the result.
- **The lookup relations live in files.** `tiers`, `quests`, the skin catalogue and the
  achievement definitions are in `shared/game-config.json` and `shared/skins/`, versioned with
  the code and read by both the backend and the browser. The copies in `problems`,
  `quest_progress` and `matches` are what tie a row to the config values it was made with.
- **One row per live match.** The engine rewrites a match's whole state after each hit;
  keeping both sides in one row makes that a single-row read and a single-row update
  (Q34 and Q35 in 04).
- **Hot reads skip joins.** `submissions.is_bot` lets stats skip bot rows without joining
  `profiles`; `rating_history.delta` and `profiles.wins/peak_rating` are read on every
  profile page; `last_seq` numbers the next event without a `max()` query.
- **Constraints keep most copies honest.** `ck_users_lower`, `ck_profiles_kind`,
  `ck_matches_winner` and `ck_rating_history_delta` make the database reject a row whose
  copy disagrees with its source. Three copies have no such guard and are kept in step by
  application code alone: `profiles.badges` against `achievements`, `submissions.is_bot`
  against `profiles.is_bot`, and `drafts.problem_slug`, which the browser sends and the
  server stores without checking it against the hand.

If those three ever drift, the BCNF forms above are the fix: compute badges from
`achievements`, join `profiles` for `is_bot`, and read the slot's card from the match.
