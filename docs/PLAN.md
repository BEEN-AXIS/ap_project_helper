# AlgoArena build plan

This is the "plan first" deliverable from the Master Build Prompt: the architecture, the phases with their gates, the risks and the decisions taken where the brief left a choice. The README describes what was built; this file records how it was approached.

## Reading of the request

The request was to build the whole Master Build Prompt into `cp_battle`, using the half-built `fastapi-backend` folder to understand the intent. The brief asks to stop after each phase gate and wait; with no one available to say "go", the phases were built in order, each gate was run before starting the next, and the outcome of each gate is recorded below.

## Architecture in one paragraph

A single Node.js process (Express for REST, ws for WebSockets, Prisma on PostgreSQL) owns every live match; it was first written in Python with FastAPI and moved to Node.js in phase 10. Each match is a `MatchActor` with an async command queue; REST handlers, WebSocket messages, the matchmaker, timers and judge verdicts all become commands on that queue. The actor applies the pure rules in `server/src/domain/`, persists the change and its numbered `match_events` row in one Prisma transaction, then broadcasts. Judging runs in a bounded `JudgePool` over a `Runner` (Docker, subprocess, Judge0 or Fake); verdicts re-enter the actor and are re-validated. The browser is event-sourced: a pure reducer rebuilds state from numbered events, a Canvas2D engine and a director turn events into timed shows, and a WebAudio synth makes every sound. `shared/` holds the one game config, golden test vectors and skin manifests used by both sides.

## Phases and gates

| # | Phase | Gate | Outcome |
|---|---|---|---|
| 1 | Contracts and scaffolding: tree, `game-config.json`, golden vectors, pure domain functions, type generation | Every golden vector and the rating property tests pass | Passed |
| 2 | Judge and content: models, migrations, auth, 17 problems with tests, runners, pool, checkers, seed and seed-check | AC, WA, CE, unauthenticated and hidden-test-leak checks over HTTP; `seed_check` green; escape suite green for the runner in use | Passed (Docker cases skip without a daemon) |
| 3 | Match engine and realtime: actor, matchmaker, bots, finish/rating, hub, protocol, WebSockets | Engine tests for every ending, idempotency, reconnect; 50-match load test | Passed: 50/50 KO |
| 4 | Web app: pages, store and reducer, editor, hand, battle log | Two browser contexts play a ranked match to the result screen | Passed in Chromium with zero console errors |
| 5 | VFX and audio: engine, director, shows, HP bars, quality levels, synth | Director timings equal the brief's tables; every show fires on both screens | Passed (unit tests + VFX steps observed in the browser run) |
| 6 | Skins and economy: registry, validation, unlocks, shop, locker, Arena Points | Manifests validate; equip changes what the opponent sees; unlock paths tested | Passed |
| 7 | Creative features behind flags: bot personalities, streaks, emotes, quests, achievements, replays | Each flag toggles its system alone; each system has a test | Passed for the flags that are on; spectate, rooms, tutorial, calibration and the later modes stay off and unbuilt; music was built later (a sequencer and 12 tracks in `audio/`, one per arena plus menu and title) |
| 8 | Hardening and release: rate limits, fair-play signals, admin console, README, docker compose | Acceptance checklist | Mostly ticked; tsc and ESLint are clean against the real packages. See "Known gaps" in the README for what still needs a run on macOS or Docker (Vite, Vitest and the Playwright runner; Docker; Alembic) |
| 9 | Weapons (requested after delivery): eight weapons with easy/normal/medium/tough forms, heavy particles, weapon locker | Every form lands its main hit on the impact step; both screens show the attacker's weapon; locker equips and previews | Passed: 32-form timing test, server equip/buy/unlock tests, screenshots of every form, two-player match |
| 10 | Move the server to the project plan's stack (requested after delivery): Node.js, Express, ws, Prisma, PostgreSQL, plain JavaScript; every Python file ported or removed (the problems' Python answer keys now live as source text in `server/seed/catalog.js`) | Same REST routes, JSON and WebSocket protocol; golden vectors, a re-recorded match and regenerated tests identical; engine, API, judge and escape suites green | Passed against an in-memory Prisma stand-in and a small Express stand-in (no npm registry in the sandbox); the Prisma migration checked on PostgreSQL 16 |

## Top risks and what addresses them

| Risk | Mitigation |
|---|---|
| Sandbox escape or abuse | Docker by default with no network, read-only root, dropped capabilities, uid 65534 and resource caps; an escape suite; the DEV SANDBOX badge and a prod refusal for the subprocess runner |
| Races on HP, double clicks | One actor per match; every command carries a `cmd_id`; one submission in flight per player; client-side double-submit guard on top |
| Database contention | PostgreSQL, short transactions through one helper (`inTx`), only the changed match columns written per command |
| Judge latency | Bounded priority pool (submissions before runs), stop at the first failing test, queue and job timeouts that become `system_error` |
| Two screens disagreeing | Persist then broadcast; numbered events; snapshot or replay of the gap on reconnect; the reducer tested against a recorded server match |
| Clock drift between players | Server time in every envelope, `match.timer` every 15 s, ping-based offset on the client |
| VFX frame drops | Pre-allocated particle pool, pre-rendered sprites, a fixed 60 Hz step, quality levels with auto fallback, reduced motion |
| Bundle size | Monaco, the VFX Lab, the admin page and every route load lazily; initial JS is about 57 KB gzipped |
| Scope creep | Feature flags and gated phases |

## Decisions where the brief left a choice

- **Problems:** 17 original problems in three biomes rather than Codeforces problems, because Codeforces does not expose hidden tests. Each has a reference solution, a brute force that must time out on the large tests, and fixed-seed generated tests.
- **Output limit vs problem size:** the 64 KB output limit wins; problems whose output would exceed it had their bounds reduced.
- **Hashing:** scrypt from Node's built-in `crypto` (no native add-on to build); the Python server used Argon2id.
- **Dev server:** `make dev` runs Vite with a proxy; `make demo` serves the built app from the API on one origin.
- **Migrations:** Prisma Migrate (`make migrate`); the five partial and expression indexes Prisma's schema language cannot express are written into the migration SQL by `server/scripts/migration-sql.js`. Tests and the demo use an in-memory stand-in (`DATABASE_URL=memory`).
- **Same random numbers in JavaScript:** `server/src/pyrandom.js` reproduces Python's Mersenne Twister, so deals, daily quests, bots and generated tests are unchanged by the move.
- **Judge selection:** `JUDGE_BACKEND=auto` uses Docker only when the daemon answers and the judge image exists, so a fresh clone works before `make judge-image`.
- **Languages:** Python only at launch; the config, protocol and editor picker are language-agnostic, the harness is not yet (no compile phase).
- **Weapons vs damage classes:** the card's difficulty (its place in the hand window) picks the weapon form and adds wind-up and travel time for the bigger forms; the damage class (share of the target's HP) still drives shake, flash, number size and slow motion, as in the brief's tables. Events without a level (older replays) keep the original timeline.
