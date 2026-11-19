"""The match actor: one asyncio task per live match, the only code allowed to
change HP, shields, hands or match status.

Every input arrives as a Command on the actor's queue and is handled one at a
time. A command is validated, applied to in-memory state (rules come from the
pure domain package), persisted together with its match_events rows in one
transaction, and only then broadcast. A rejected command changes nothing and
broadcasts nothing. Judging never blocks the actor: verdicts come back later
as their own command and are re-validated.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, delete, select

from app.core.db import run_db
from app.core.errors import AppError, RuleError
from app.domain import damage as dmg
from app.domain import hand as handlib
from app.domain import powerups
from app.domain.hand import HandState
from app.domain.outcome import SideEnd, classify
from app.judge.runner import JobResult, TestVerdict
from app.models import Draft, Match, MatchEvent, Side, Submission, utcnow
from app.realtime.hub import Connection, envelope

if TYPE_CHECKING:
    from app.engine.service import MatchService

log = logging.getLogger("algoarena.actor")

LIVE_STATES = ("starting", "live")
STAT_KEYS = (
    "submissions", "accepted", "backfires", "recoil_taken", "damage_taken", "biggest_hit", "crits", "heroic_hits",
    "hits_stretching", "blocks_absorbed", "hints_used", "blocks_used", "streak", "max_streak", "fastest_solve_ms",
    "accepted_run_after", "rerolls_used", "system_errors",
)


@dataclass
class Command:
    kind: str
    side: int
    data: dict[str, Any] = field(default_factory=dict)
    cmd_id: str | None = None
    future: asyncio.Future[Any] | None = None

    def reply(self, value: Any) -> None:
        if self.future and not self.future.done():
            self.future.set_result(value)

    def fail(self, exc: Exception) -> None:
        if self.future and not self.future.done():
            self.future.set_exception(exc)


@dataclass
class Ev:
    type: str
    data: dict[str, Any]
    vis: str
    seq: int
    t_ms: int


@dataclass
class SideRuntime:
    inflight: Submission | None = None
    inflight_slot: int | None = None
    cooldown_until_ms: int = 0
    cmd_cache: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    disconnect_timer: Any = None
    dealt_at_ms: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    last_emote_ms: int = -10**9
    judging_task: asyncio.Task[None] | None = None
    ever_connected: bool = False


class MatchActor:
    def __init__(self, svc: MatchService, m: Match) -> None:
        self.svc = svc
        self.cfg = svc.cfg
        self.clock = svc.clock
        self.hub = svc.hub
        self.m = m
        self.id = m.id
        self.queue: asyncio.Queue[Command] = asyncio.Queue()
        self.decks: dict[int, list[str]] = {int(k): list(v) for k, v in (m.decks or {}).items()}
        self.hands: dict[int, HandState] = {1: HandState.from_json(m.player1_hand), 2: HandState.from_json(m.player2_hand)}
        self.rt = {1: SideRuntime(), 2: SideRuntime()}
        self.created_ms = self.clock.now_ms()
        self.live_ms: int | None = None
        self.timers: dict[str, Any] = {}
        self.task: asyncio.Task[None] | None = None
        self.busy = False
        self.stopped = False
        self.finished = m.status not in LIVE_STATES
        self.rng = random.Random(m.seed)
        self.bots: dict[int, Any] = {}
        # per-command scratch
        self._events: list[Ev] = []
        self._transient: list[tuple[int, dict[str, Any]]] = []
        self._tx: list[Callable[[Session], None]] = []
        self._after: list[Callable[[], None]] = []
        self._pending_submissions: list[Submission] = []

    # ------------------------------------------------------------------ plumbing
    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name=f"match-{self.id[:8]}")
        if not self.finished:
            self._schedule("connect_timeout", self.cfg.match.connect_grace_s, "connect_timeout")
            for s in (1, 2):
                if self.side(s).is_bot:
                    self.side(s).connected = True
                    self.rt[s].ever_connected = True
            from app.engine.bots import make_brain

            for s in (1, 2):
                brain = make_brain(self, s)
                if brain is not None:
                    self.bots[s] = brain
            self._maybe_countdown()

    async def stop(self) -> None:
        self.stopped = True
        for t in list(self.timers.values()):
            with contextlib.suppress(Exception):
                t.cancel()
        self.timers.clear()
        for rt in self.rt.values():
            if rt.judging_task and not rt.judging_task.done():
                rt.judging_task.cancel()
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task

    def enqueue(self, cmd: Command) -> None:
        if not self.stopped:
            self.queue.put_nowait(cmd)

    def enqueue_cmd(self, kind: str, side: int, data: dict[str, Any] | None = None) -> None:
        self.enqueue(Command(kind, side, data or {}))

    async def send(self, kind: str, side: int, data: dict[str, Any] | None = None, cmd_id: str | None = None) -> Any:
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.enqueue(Command(kind, side, data or {}, cmd_id, fut))
        return await asyncio.wait_for(fut, 30)

    async def settle(self, rounds: int = 200) -> None:
        """Tests: wait until the queue is drained and no judging is in flight."""
        for _ in range(rounds):
            await asyncio.sleep(0)
            judging = any(rt.judging_task and not rt.judging_task.done() for rt in self.rt.values())
            if self.queue.empty() and not self.busy and not judging and self.svc.pool.idle:
                await asyncio.sleep(0)
                if self.queue.empty() and not self.busy:
                    return
            await asyncio.sleep(0.002)

    def side(self, n: int) -> Side:
        return Side(self.m, n)

    def side_of(self, profile_id: int) -> int | None:
        if self.m.player1_profile_id == profile_id and not self.m.player1_is_bot:
            return 1
        if self.m.player2_profile_id == profile_id and not self.m.player2_is_bot:
            return 2
        return None

    def now(self) -> int:
        return self.clock.now_ms()

    def elapsed_ms(self) -> int:
        if self.live_ms is None:
            return 0
        if self.finished:
            return self.m.elapsed_ms
        return max(0, self.now() - self.live_ms)

    def _schedule(self, key: str, delay_s: float, kind: str, **data: Any) -> None:
        old = self.timers.pop(key, None)
        if old is not None:
            old.cancel()
        self.timers[key] = self.clock.call_later(delay_s, lambda: self.enqueue(Command("tick", 0, {"kind": kind, **data})))

    def _cancel(self, key: str) -> None:
        t = self.timers.pop(key, None)
        if t is not None:
            t.cancel()

    def emit(self, type_: str, data: dict[str, Any], vis: str = "both") -> Ev:
        self.m.last_seq += 1
        ev = Ev(type_, data, vis, self.m.last_seq, self.now() - self.created_ms)
        self._events.append(ev)
        return ev

    def transient(self, side: int, type_: str, data: dict[str, Any]) -> None:
        self._transient.append((side, envelope(type_, data)))

    def stat(self, side: int, key: str, delta: int = 1) -> None:
        s = dict(self.side(side).stats or {})
        s[key] = s.get(key, 0) + delta
        self.side(side).stats = s

    def stat_set(self, side: int, key: str, value: Any) -> None:
        s = dict(self.side(side).stats or {})
        s[key] = value
        self.side(side).stats = s

    def stat_get(self, side: int, key: str, default: Any = 0) -> Any:
        return (self.side(side).stats or {}).get(key, default)

    # ------------------------------------------------------------------ main loop
    async def run(self) -> None:
        while not self.stopped:
            cmd = await self.queue.get()
            self.busy = True
            try:
                await self._process(cmd)
            except Exception as e:  # never let one command kill the match
                log.exception("actor command failed", exc_info=e)
                cmd.fail(AppError("server_error", "Internal error"))
            finally:
                self.busy = False
                self.queue.task_done()

    async def _process(self, cmd: Command) -> None:
        rt = self.rt.get(cmd.side)
        if cmd.cmd_id and rt is not None and cmd.cmd_id in rt.cmd_cache:
            cached = rt.cmd_cache[cmd.cmd_id]
            if isinstance(cached, Exception):
                cmd.fail(cached)
            else:
                cmd.reply(cached)
            return
        self._events, self._transient, self._tx, self._after, self._pending_submissions = [], [], [], [], []
        try:
            if cmd.kind == "join":
                result = await self._join(cmd)
            else:
                handler = getattr(self, f"_cmd_{cmd.kind}", None)
                if handler is None:
                    raise RuleError("validation", f"unknown command {cmd.kind}")
                result = handler(cmd)
        except RuleError as e:
            if cmd.cmd_id and rt is not None:
                self._remember(rt, cmd.cmd_id, e)
            cmd.fail(e)
            return
        if self._events or self._tx or self._pending_submissions:
            try:
                await run_db(self._persist)
            except Exception as e:
                log.exception("persist failed; aborting the match", exc_info=e)
                cmd.fail(AppError("server_error", "Could not save the match"))
                await self._fail_safe()
                return
            for ev in self._events:
                await self.hub.broadcast(self.id, ev.vis, envelope(ev.type, ev.data, ev.seq))
        for side, msg in self._transient:
            await self.hub.send_side(self.id, side, msg)
        for fn in self._after:
            fn()
        if cmd.cmd_id and rt is not None:
            self._remember(rt, cmd.cmd_id, result)
        cmd.reply(result)

    async def _fail_safe(self) -> None:
        """In-memory state may no longer match the database: abort the match."""
        if self.finished:
            return
        self._events, self._transient, self._tx, self._after, self._pending_submissions = [], [], [], [], []
        self._abort("server_error")
        mid, last_seq = self.id, self.m.last_seq

        def work(s: Session) -> None:
            row = s.get(Match, mid)
            if row is not None:
                row.status, row.end_reason, row.outcome = "aborted", "aborted", "aborted"
                row.result = self.m.result
                row.last_seq = last_seq
                s.add(row)

        try:
            await run_db(work)
        except Exception:  # pragma: no cover
            log.exception("could not record the aborted match")
        for ev in self._events:
            await self.hub.broadcast(self.id, ev.vis, envelope(ev.type, ev.data, ev.seq))
        for fn in self._after:
            fn()

    @staticmethod
    def _remember(rt: SideRuntime, cmd_id: str, value: Any) -> None:
        rt.cmd_cache[cmd_id] = value
        while len(rt.cmd_cache) > 256:
            rt.cmd_cache.popitem(last=False)

    def _persist(self, s: Session) -> None:
        for fn in self._tx:
            fn(s)
        s.merge(self.m)
        for sub in self._pending_submissions:
            merged = s.merge(sub)
            s.flush()
            sub.id = merged.id
        for ev in self._events:
            if ev.data.get("submission_id") == "pending" and self._pending_submissions:
                ev.data["submission_id"] = self._pending_submissions[0].id
            s.add(MatchEvent(match_id=self.id, seq=ev.seq, t_ms=ev.t_ms, type=ev.type, payload=ev.data, visibility=ev.vis))

    # ------------------------------------------------------------------ views
    def player_view(self, n: int) -> dict[str, Any]:
        sd = self.side(n)
        shield = sd.shield_until_ms
        active = powerups.shield_active(shield, self.now())
        return {
            "side": n, "profile_id": sd.profile_id, "name": sd.name, "rating": sd.rating, "tier": sd.tier,
            "max_hp": sd.max_hp, "hp": sd.hp, "skins": sd.skins or {}, "is_bot": sd.is_bot,
            "connected": bool(sd.connected), "hits_landed": sd.hits_landed, "damage_dealt": sd.damage_dealt,
            "shield_ms_left": max(0, shield - self.now()) if active and shield else 0,
            "judging": self.rt[n].inflight is not None,
        }

    def card(self, n: int, slot: int) -> dict[str, Any]:
        hand = self.hands[n]
        slug = hand.slots[slot]
        tier = hand.tiers[slot]
        if slug is None:
            return {"slot": slot, "tier": tier, "problem": None, "preview": None, "pending": True}
        p = self.svc.problems.get(slug)
        assert p is not None, slug
        pv = dmg.compute_preview(self.side(n).tier, p.tier, p.base_damage, p.base_recoil, self.cfg)
        revealed = (self.side(n).hints_revealed or {}).get(slug, 0)
        return {
            "slot": slot, "tier": tier, "pending": False,
            "problem": {"slug": p.slug, "title": p.title, "tier": p.tier, "biome": p.biome,
                        "tags": p.tags if revealed >= 1 else []},
            "preview": {"damage": pv.damage, "recoil": pv.recoil, "tier_diff": pv.tier_diff, "scenario": pv.scenario,
                        "crit": pv.crit, "dmg_pct": pv.dmg_pct, "recoil_pct": pv.recoil_pct},
            "hints_revealed": revealed,
        }

    def hand_view(self, n: int) -> list[dict[str, Any]]:
        return [self.card(n, i) for i in range(len(self.hands[n].slots))]

    def clock_view(self) -> dict[str, Any]:
        return {
            "status": self.m.status, "elapsed_ms": self.elapsed_ms(), "server_time_ms": self.clock.wall_ms(),
            "max_ms": self.cfg.match.max_minutes * 60_000, "bracket": self._bracket(),
        }

    def _bracket(self) -> str:
        from app.domain.rating import speed_bracket

        return speed_bracket(self.elapsed_ms() // 1000, self.cfg)

    def snapshot(self, n: int) -> dict[str, Any]:
        sd = self.side(n)
        rt = self.rt[n]
        revealed = sd.hints_revealed or {}
        hints: dict[str, list[str]] = {}
        for slug, lvl in revealed.items():
            p = self.svc.problems.get(slug)
            if p:
                hints[slug] = p.hints[:lvl]
        next_reroll_ms = 0
        if sd.last_reroll_ms is not None:
            next_reroll_ms = max(0, sd.last_reroll_ms + self.cfg.hand.reroll_gap_s * 1000 - self.now())
        return {
            "match": {"id": self.id, "mode": self.m.mode, "map": self.m.map, "status": self.m.status,
                      "stage": self.stage_view()},
            "you": n,
            "players": [self.player_view(1), self.player_view(2)],
            "clock": self.clock_view(),
            "hand": self.hand_view(n),
            "charges": {"blocks_left": sd.blocks_left, "hints_left": sd.hints_left, "rerolls_left": sd.rerolls_left,
                        "next_reroll_ms": next_reroll_ms},
            "hints": hints,
            "cooldown_ms": max(0, rt.cooldown_until_ms - self.now()),
            "inflight": ({"submission_id": rt.inflight.id, "slot": rt.inflight_slot} if rt.inflight else None),
            "seq": self.m.last_seq,
            "result": self.m.result if self.finished else None,
        }

    def stage_view(self) -> dict[str, Any]:
        owner = self.m.stage_owner_side
        return {"theme": self.m.stage_theme, "owner_side": owner, "owner_name": self.side(owner).name if owner else None}

    def started_payload(self) -> dict[str, Any]:
        return {"players": [self.player_view(1), self.player_view(2)], "mode": self.m.mode, "map": self.m.map,
                "stage": self.stage_view(), "clock": self.clock_view()}

    # ------------------------------------------------------------------ connect / resume
    async def _join(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        conn: Connection = cmd.data["conn"]
        last_seq = int(cmd.data.get("last_seq") or 0)
        old = self.hub.attach(self.id, n, conn)
        if old is not None:
            await old.send(envelope("session.moved", {"reason": "session_moved", "message": "This match was opened in another tab."}))
            await old.close(4001)
        sd = self.side(n)
        rt = self.rt[n]
        was_connected = bool(sd.connected)
        sd.connected = True
        rt.ever_connected = True
        if rt.disconnect_timer is not None:
            self._cancel(f"disconnect:{n}")
            rt.disconnect_timer = None
            if self.m.status == "live" and not was_connected:
                self.emit("player.reconnected", {"side": n}, f"p{3 - n}")
        # Resume: replay missed events this side may see, or a snapshot.
        gap = self.m.last_seq - last_seq
        if last_seq <= 0 or gap > self.cfg.match.snapshot_gap:
            await conn.send(envelope("state.snapshot", self.snapshot(n), self.m.last_seq))
        elif gap > 0:
            missed = await run_db(_load_events, self.id, last_seq, n)
            for e in missed:
                await conn.send(envelope(e["type"], e["payload"], e["seq"]))
        if not self.finished:
            self._maybe_countdown()
        return {"ok": True}

    def _cmd_leave(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        conn = cmd.data["conn"]
        if not self.hub.detach(self.id, n, conn):
            return {"ok": True}  # an old, replaced socket
        sd = self.side(n)
        sd.connected = False
        if self.m.status == "live":
            grace = self.cfg.match.disconnect_grace_s
            self.emit("player.disconnected", {"side": n, "grace_s": grace}, f"p{3 - n}")
            self.rt[n].disconnect_timer = True
            self._schedule(f"disconnect:{n}", grace, "disconnect_timeout", side=n)
        return {"ok": True}

    def _maybe_countdown(self) -> None:
        if self.m.status != "starting" or "countdown" in self.timers:
            return
        if not (self.side(1).connected and self.side(2).connected):
            return
        self._cancel("connect_timeout")
        n = self.cfg.match.countdown_s
        self.emit("match.countdown", {"n": n})
        self._schedule("countdown", 1, "countdown", n=n - 1)

    # ------------------------------------------------------------------ ticks
    def _cmd_tick(self, cmd: Command) -> Any:
        kind = cmd.data["kind"]
        if kind == "countdown":
            self.timers.pop("countdown", None)
            n = cmd.data["n"]
            if self.m.status != "starting":
                return None
            self.emit("match.countdown", {"n": n})
            if n > 0:
                self.timers["countdown"] = self.clock.call_later(
                    1, lambda: self.enqueue(Command("tick", 0, {"kind": "countdown", "n": n - 1})))
            else:
                self._go_live()
            return None
        if self.finished:
            return None
        if kind == "connect_timeout":
            if self.m.status == "starting":
                absent = [s for s in (1, 2) if not self.rt[s].ever_connected]
                self._abort("no_show", strike_sides=absent or [1, 2])
        elif kind == "timer_end":
            if self.m.status == "live":
                self._end("timer")
        elif kind == "timer_broadcast":
            if self.m.status == "live":
                self.emit("match.timer", self.clock_view())
                self._schedule("timer_broadcast", self.cfg.match.timer_broadcast_s, "timer_broadcast")
        elif kind == "shield_expire":
            n = cmd.data["side"]
            sd = self.side(n)
            if sd.shield_until_ms is not None and sd.shield_until_ms <= self.now():
                sd.shield_until_ms = None
                self.emit("shield.expired", {"side": n})
        elif kind == "redeal":
            n, slot = cmd.data["side"], cmd.data["slot"]
            if self.m.status == "live" and self.hands[n].slots[slot] is None:
                self.hands[n] = handlib.fill_slot(self.hands[n], self.decks, slot)
                self.side(n).hand = self.hands[n].to_json()
                self.rt[n].dealt_at_ms[slot] = self.now()
                self.emit("card.dealt", {"card": self.card(n, slot)}, f"p{n}")
        elif kind == "disconnect_timeout":
            n = cmd.data["side"]
            self.timers.pop(f"disconnect:{n}", None)
            if self.m.status == "live" and not self.side(n).connected:
                if not self.side(3 - n).connected and not self.side(3 - n).is_bot:
                    self._abort("both_disconnected")
                elif self._early_leave():
                    self._abort("early_leave", strike_sides=[n])
                else:
                    self._end("disconnect", leaver=n)
        elif kind == "bot":
            n = cmd.data["side"]
            brain = self.bots.get(n)
            if brain is not None and self.m.status == "live":
                brain.on_tick(cmd.data)
        elif kind == "bot_verdict":
            n = cmd.data["side"]
            if self.rt[n].inflight is not None and self.rt[n].inflight.id == cmd.data["submission_id"]:
                self._resolve(n, cmd.data["result"], cmd.data["total"])
        return None

    def _go_live(self) -> None:
        self.m.status = "live"
        self.m.start_time = utcnow()
        self.live_ms = self.now()
        for n in (1, 2):
            self.rt[n].dealt_at_ms = [self.live_ms] * len(self.hands[n].slots)
        self.emit("match.started", self.started_payload())
        for n in (1, 2):
            if not self.side(n).is_bot:
                self.emit("hand.updated", {"cards": self.hand_view(n)}, f"p{n}")
        self._schedule("timer_end", self.cfg.match.max_minutes * 60, "timer_end")
        self._schedule("timer_broadcast", self.cfg.match.timer_broadcast_s, "timer_broadcast")
        for brain in self.bots.values():
            self._after.append(brain.on_live)

    # ------------------------------------------------------------------ validation helpers
    def _require_live(self) -> None:
        if self.m.status != "live" or self.finished:
            raise RuleError("match_not_live", "The match is not live")

    def _require_card(self, n: int, slot: int) -> str:
        if not 0 <= slot < len(self.hands[n].slots):
            raise RuleError("not_in_hand", "No such card slot")
        slug = self.hands[n].slots[slot]
        if slug is None:
            raise RuleError("not_in_hand", "That card is being re-dealt")
        return slug

    def card_slug(self, n: int, slot: int) -> str:
        """Read-only lookup for the Run endpoint (no state change)."""
        return self._require_card(n, slot)

    # ------------------------------------------------------------------ submit
    def _cmd_submit(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        self._require_live()
        slot = int(cmd.data["slot"])
        slug = self._require_card(n, slot)
        if cmd.data.get("problem") and cmd.data["problem"] != slug:
            raise RuleError("not_in_hand", "That card is no longer in your hand")
        rt = self.rt[n]
        if rt.inflight is not None:
            raise RuleError("busy", "You already have a submission being judged")
        wait = rt.cooldown_until_ms - self.now()
        if wait > 0:
            raise RuleError("cooldown", "Submit is cooling down", {"retry_after": wait / 1000})
        code = cmd.data["code"]
        language = cmd.data.get("language", "python")
        simulated = bool(cmd.data.get("simulated"))
        if not simulated:
            from app.services.judging import validate_code, validate_language

            validate_language(language, self.cfg)
            try:
                validate_code(code, self.cfg)
            except AppError as e:
                raise RuleError(e.code, e.message) from None
        p = self.svc.problems.get(slug)
        assert p is not None
        sub = Submission(match_id=self.id, profile_id=self.side(n).profile_id, problem_id=p.id, slot=slot,
                         language=language, code=code, cmd_id=cmd.cmd_id or f"auto-{uuid.uuid4().hex}", is_bot=simulated)
        self._pending_submissions.append(sub)
        rt.inflight = sub
        rt.inflight_slot = slot
        self.stat(n, "submissions")
        total = len(p.all_tests)
        self.emit("submission.accepted", {"submission_id": "pending", "slot": slot, "problem": slug, "total": total,
                                          "queue_position": self.svc.pool.queued}, f"p{n}")
        self.transient(3 - n, "opponent.activity", {"side": n, "state": "judging"})
        if simulated:
            self._after.append(lambda: self.bots[n].on_submitted(sub, total) if n in self.bots else None)
        else:
            self._after.append(lambda: self._start_judging(n, sub, p, language, code))
        return {"submission_id_pending": True, "slot": slot, "_sub": sub}

    def _start_judging(self, n: int, sub: Submission, problem: Any, language: str, code: str) -> None:
        from app.services.judging import judge_full

        async def on_progress(v: TestVerdict) -> None:
            if self.rt[n].inflight is sub:
                await self.hub.send_side(self.id, n, envelope("submission.progress", {
                    "submission_id": sub.id, "index": v.index, "code": v.code,
                    "passed": v.index + 1 if v.code == "AC" else v.index, "total": len(problem.all_tests)}))

        async def work() -> None:
            try:
                res, total = await judge_full(self.svc.pool, self.cfg, problem, language, code, on_progress)
            except AppError:
                res, total = JobResult(compile_error=None, system_error=True, system_message="judge busy"), len(problem.all_tests)
            except asyncio.CancelledError:
                return
            except Exception as e:  # pragma: no cover
                log.exception("judging failed", exc_info=e)
                res, total = JobResult(compile_error=None, system_error=True, system_message="judge failure"), len(problem.all_tests)
            self.enqueue(Command("verdict", n, {"submission": sub, "result": res, "total": total}))

        self.rt[n].judging_task = asyncio.create_task(work())

    def _cmd_verdict(self, cmd: Command) -> None:
        n = cmd.side
        sub: Submission = cmd.data["submission"]
        if self.rt[n].inflight is not sub:
            return None
        self._resolve(n, cmd.data["result"], cmd.data["total"])
        return None

    def _resolve(self, n: int, res: JobResult, total: int) -> None:
        """A verdict re-enters the actor: re-validate, then hit, block or backfire."""
        rt = self.rt[n]
        sub = rt.inflight
        assert sub is not None
        slot = rt.inflight_slot if rt.inflight_slot is not None else sub.slot
        rt.inflight = None
        rt.inflight_slot = None
        self._pending_submissions.append(sub)
        verdict, failed, passed = res.summary(total)
        sub.verdict = verdict
        sub.failed_test = failed
        sub.tests_passed = passed
        sub.tests_total = total
        sub.time_ms = max((v.time_ms for v in res.verdicts), default=0)
        sub.memory_kb = max((v.memory_kb for v in res.verdicts), default=0)
        other = 3 - n
        base = {"submission_id": sub.id, "slot": slot, "verdict": verdict, "failed_test": failed, "passed": passed,
                "total": total, "time_ms": sub.time_ms, "memory_kb": sub.memory_kb,
                "compile_error": (res.compile_error or None)}
        self.transient(other, "opponent.activity", {"side": n, "state": "editor"})

        if self.finished or self.m.status != "live":
            sub.status = "void"
            self.emit("submission.verdict", {**base, "void": True, "reason": "match_ended"}, f"p{n}")
            return
        if verdict == "SE":
            sub.status = "void"
            self.stat(n, "system_errors")
            self.emit("submission.verdict", {**base, "void": True, "reason": "system_error"}, f"p{n}")
            if self.stat_get(n, "system_errors") >= self.cfg.judge.system_error_flag_after:
                self._tx.append(lambda s: _flag(s, self.id, self.side(n).profile_id, "judge_system_errors", {"count": self.stat_get(n, "system_errors")}))
            return

        sub.status = "done"
        slug = self.hands[n].slots[slot]
        p = self.svc.problems.by_id.get(sub.problem_id)
        assert p is not None
        att, dfn = self.side(n), self.side(other)
        pv = dmg.compute_preview(att.tier, p.tier, p.base_damage, p.base_recoil, self.cfg)
        sub.crit = pv.crit
        rt.cooldown_until_ms = self.now() + self.cfg.match.submit_cooldown_s * 1000
        cooldown_ms = self.cfg.match.submit_cooldown_s * 1000

        if verdict == "AC":
            att.hits_landed = att.hits_landed + 1
            self.stat(n, "accepted")
            self.stat(n, "accepted_run_after")
            self.stat(n, "streak")
            self.stat_set(n, "max_streak", max(self.stat_get(n, "max_streak"), self.stat_get(n, "streak")))
            solve_ms = self.now() - self.rt[n].dealt_at_ms[slot]
            best = self.stat_get(n, "fastest_solve_ms", None)
            if best is None or solve_ms < best:
                self.stat_set(n, "fastest_solve_ms", solve_ms)
            if pv.tier_diff <= -1:
                self.stat(n, "hits_stretching")
            if pv.tier_diff <= -4:
                self.stat(n, "heroic_hits")
            if pv.crit:
                self.stat(n, "crits")
            cls = dmg.damage_class(pv.damage, dfn.max_hp, self.cfg)
            self.emit("submission.verdict", {**base, "void": False, "damage": pv.damage, "recoil": 0,
                                             "cooldown_ms": cooldown_ms}, f"p{n}")
            if powerups.shield_active(dfn.shield_until_ms, self.now()):
                dfn.shield_until_ms = None
                self._cancel(f"shield:{other}")
                sub.blocked = True
                self.stat(other, "blocks_absorbed")
                self.emit("attack.blocked", {"attacker": n, "defender": other, "prevented_damage": pv.damage,
                                             "damage_class": cls, "crit": pv.crit, "scenario": pv.scenario,
                                             "problem": slug, "hits_landed": att.hits_landed})
            else:
                full_before = dfn.hp == dfn.max_hp
                dfn.hp = dmg.apply_hp_loss(dfn.hp, pv.damage)
                att.damage_dealt = att.damage_dealt + pv.damage  # overkill counts in full
                sub.damage = pv.damage
                self.stat(other, "damage_taken", pv.damage)
                self.stat_set(n, "biggest_hit", max(self.stat_get(n, "biggest_hit"), pv.damage))
                if full_before and dfn.hp == 0:
                    self.stat_set(n, "one_shot", True)
                self._track_low(other)
                self.emit("attack.landed", {"attacker": n, "defender": other, "damage": pv.damage, "damage_class": cls,
                                            "crit": pv.crit, "scenario": pv.scenario, "tier_diff": pv.tier_diff,
                                            "problem": slug, "defender_hp": dfn.hp,
                                            "attacker_damage_dealt": att.damage_dealt, "hits_landed": att.hits_landed})
            # The card is spent; the slot gets the next problem of its tier later.
            self.hands[n] = handlib.consume_slot(self.hands[n], slot)
            att.hand = self.hands[n].to_json()
            self.emit("hand.updated", {"cards": self.hand_view(n)}, f"p{n}")
            self._clear_draft(n, slot)
            self._schedule(f"redeal:{n}:{slot}", self.cfg.hand.redeal_ms / 1000, "redeal", side=n, slot=slot)
            if dfn.hp == 0:
                self._end("ko")
        else:
            att.hp = dmg.apply_hp_loss(att.hp, pv.recoil)
            sub.recoil = pv.recoil
            self.stat(n, "backfires")
            self.stat(n, "recoil_taken", pv.recoil)
            self.stat_set(n, "streak", 0)
            self.stat_set(n, "accepted_run_after", 0)
            self.stat_set(n, "failed_any", True)
            self._track_low(n)
            cls = dmg.damage_class(pv.recoil, att.max_hp, self.cfg)
            self.emit("submission.verdict", {**base, "void": False, "damage": 0, "recoil": pv.recoil,
                                             "cooldown_ms": cooldown_ms}, f"p{n}")
            self.emit("attack.backfire", {"attacker": n, "recoil": pv.recoil, "recoil_class": cls, "verdict": verdict,
                                          "problem": slug, "attacker_hp": att.hp, "crit": pv.crit, "scenario": pv.scenario})
            if att.hp == 0:
                self.stat_set(n, "ko_by_recoil", True)
                self._end("ko")
        if not self.finished:
            for s, brain in self.bots.items():
                brain.after_verdict(s == n, verdict)

    def _track_low(self, n: int) -> None:
        sd = self.side(n)
        low = self.stat_get(n, "lowest_hp", sd.max_hp)
        self.stat_set(n, "lowest_hp", min(low, sd.hp))

    def _clear_draft(self, n: int, slot: int) -> None:
        pid = self.side(n).profile_id
        mid = self.id
        self._tx.append(lambda s: s.exec(delete(Draft).where(Draft.match_id == mid, Draft.profile_id == pid, Draft.slot == slot)))  # type: ignore[arg-type]

    # ------------------------------------------------------------------ powerups and actions
    def _cmd_block(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        self._require_live()
        sd = self.side(n)
        if not powerups.has_charge(sd.blocks_left) or sd.blocks_left == 0:
            raise RuleError("no_charges", "No Block charges left")
        if powerups.shield_active(sd.shield_until_ms, self.now()):
            raise RuleError("conflict", "Your shield is already up")
        sd.blocks_left = powerups.spend(sd.blocks_left)
        sd.shield_until_ms = powerups.shield_until(self.now(), self.cfg)
        self.stat(n, "blocks_used")
        window_ms = self.cfg.powerups.block.window_s * 1000
        self.emit("powerup.used", {"side": n, "kind": "block", "shield_ms": window_ms, "charges_left": sd.blocks_left})
        self._schedule(f"shield:{n}", self.cfg.powerups.block.window_s, "shield_expire", side=n)
        return {"ok": True, "charges_left": sd.blocks_left}

    def _cmd_hint(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        self._require_live()
        slot = int(cmd.data["slot"])
        slug = self._require_card(n, slot)
        sd = self.side(n)
        if not powerups.has_charge(sd.hints_left):
            raise RuleError("no_charges", "No Hint charges left")
        revealed = dict(sd.hints_revealed or {})
        level = powerups.next_hint_level(revealed.get(slug, 0), self.cfg)
        if level is None:
            raise RuleError("conflict", "Every hint for this card is already revealed")
        p = self.svc.problems.get(slug)
        assert p is not None
        revealed[slug] = level
        sd.hints_revealed = revealed
        sd.hints_left = powerups.spend(sd.hints_left)
        self.stat(n, "hints_used")
        text = p.hints[level - 1] if level - 1 < len(p.hints) else ""
        self.emit("hint.revealed", {"slot": slot, "problem": slug, "level": level, "text": text,
                                    "tags": p.tags if level == 1 else None}, f"p{n}")
        self.emit("powerup.used", {"side": n, "kind": "hint", "charges_left": sd.hints_left})
        return {"ok": True, "level": level, "text": text, "charges_left": sd.hints_left}

    def _cmd_reroll(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        self._require_live()
        slot = int(cmd.data["slot"])
        self._require_card(n, slot)
        sd = self.side(n)
        rt = self.rt[n]
        if sd.rerolls_left <= 0:
            raise RuleError("no_charges", "No rerolls left")
        if rt.inflight is not None and rt.inflight_slot == slot:
            raise RuleError("busy", "That card is being judged")
        if sd.last_reroll_ms is not None:
            wait = sd.last_reroll_ms + self.cfg.hand.reroll_gap_s * 1000 - self.now()
            if wait > 0:
                raise RuleError("cooldown", "Reroll is cooling down", {"retry_after": wait / 1000})
        before = self.hands[n].slots[slot]
        self.hands[n] = handlib.reroll_slot(self.hands[n], self.decks, slot)
        if self.hands[n].slots[slot] == before:
            raise RuleError("conflict", "No other problem of that tier to swap in")
        sd.hand = self.hands[n].to_json()
        sd.rerolls_left = sd.rerolls_left - 1
        sd.last_reroll_ms = self.now()
        self.rt[n].dealt_at_ms[slot] = self.now()
        self.stat(n, "rerolls_used")
        self._clear_draft(n, slot)
        self.emit("hand.updated", {"cards": self.hand_view(n), "rerolled": slot, "rerolls_left": sd.rerolls_left}, f"p{n}")
        return {"ok": True, "rerolls_left": sd.rerolls_left}

    def _cmd_forfeit(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        if self.finished:
            raise RuleError("match_not_live", "The match is over")
        if self.m.status == "starting":
            self._abort("early_leave", strike_sides=[n])
        elif self._early_leave():
            self._abort("early_leave", strike_sides=[n])
        else:
            self._end("forfeit", leaver=n)
        return {"ok": True}

    def _cmd_emote(self, cmd: Command) -> dict[str, Any]:
        n = cmd.side
        if not self.cfg.feature("emotes"):
            raise RuleError("forbidden", "Emotes are switched off")
        if self.finished:
            raise RuleError("match_not_live", "The match is over")
        emote = cmd.data.get("id")
        if emote not in self.cfg.emotes:
            raise RuleError("validation", "Unknown emote")
        rt = self.rt[n]
        wait = rt.last_emote_ms + self.cfg.match.emote_cooldown_s * 1000 - self.now()
        if wait > 0:
            raise RuleError("cooldown", "Emote is cooling down", {"retry_after": wait / 1000})
        rt.last_emote_ms = self.now()
        self.emit("emote", {"side": n, "id": emote})
        return {"ok": True}

    def _cmd_activity(self, cmd: Command) -> None:
        state = cmd.data.get("state")
        if state in ("arena", "editor") and self.m.status == "live" and self.rt[cmd.side].inflight is None:
            self.transient(3 - cmd.side, "opponent.activity", {"side": cmd.side, "state": state})
        return None

    def _cmd_abort(self, cmd: Command) -> dict[str, Any]:
        if self.finished:
            raise RuleError("match_not_live", "The match is over")
        self._abort(cmd.data.get("reason", "admin"))
        return {"ok": True}

    def _early_leave(self) -> bool:
        """Leaving in the first 30 s before anyone submitted aborts the match."""
        if self.m.status != "live" or self.live_ms is None:
            return True
        no_submissions = all(self.stat_get(s, "submissions") == 0 for s in (1, 2))
        return no_submissions and self.elapsed_ms() < self.cfg.match.early_leave_s * 1000

    # ------------------------------------------------------------------ ending
    def _finish_common(self) -> None:
        self.finished = True
        self.m.end_time = utcnow()
        self.m.elapsed_ms = max(0, self.now() - self.live_ms) if self.live_ms is not None else 0
        for key in list(self.timers):
            self._cancel(key)
        for n in (1, 2):
            rt = self.rt[n]
            if rt.inflight is not None:
                sub = rt.inflight
                sub.status = "void"
                self._pending_submissions.append(sub)
                self.emit("submission.verdict", {"submission_id": sub.id, "slot": rt.inflight_slot, "verdict": None,
                                                 "void": True, "reason": "match_ended"}, f"p{n}")
                rt.inflight = None
                rt.inflight_slot = None
            if rt.judging_task and not rt.judging_task.done():
                rt.judging_task.cancel()
        mid = self.id
        self._tx.append(lambda s: s.exec(delete(Draft).where(Draft.match_id == mid)))  # type: ignore[arg-type]
        self._after.append(self.svc.on_finished_soon(self))

    def _abort(self, reason: str, strike_sides: list[int] | None = None) -> None:
        self.m.status = "aborted"
        self.m.end_reason = "aborted"
        self.m.outcome = "aborted"
        self._finish_common()
        payload: dict[str, Any] = {"outcome": "aborted", "end_reason": "aborted", "reason": reason, "winner_side": None,
                                   "labels": {}, "final_hp": {"1": self.m.player1_hp, "2": self.m.player2_hp},
                                   "sides": {}, "elapsed_ms": self.m.elapsed_ms}
        self.m.result = payload
        strikes = [self.side(s).profile_id for s in (strike_sides or []) if not self.side(s).is_bot]
        if strikes and self.m.mode in ("ranked", "friendly"):
            from app.engine.finish import apply_strikes

            self._tx.append(lambda s: apply_strikes(s, strikes, self.cfg))
        self.emit("match.ended", payload)

    def _end(self, reason: str, leaver: int | None = None) -> None:
        a, b = self.side(1), self.side(2)
        o = classify(reason, SideEnd(a.hp, a.hits_landed, bool(self.stat_get(1, "ko_by_recoil", False)), leaver == 1),  # type: ignore[arg-type]
                     SideEnd(b.hp, b.hits_landed, bool(self.stat_get(2, "ko_by_recoil", False)), leaver == 2))
        if o.outcome == "aborted":
            self._abort(reason)
            return
        self.m.status = "finished"
        self.m.end_reason = o.end_reason
        self.m.outcome = o.outcome
        self.m.winner_side = o.winner_side
        self.m.labels = {str(k): v for k, v in o.labels.items()}
        self._finish_common()
        payload: dict[str, Any] = {
            "outcome": o.outcome, "winner_side": o.winner_side, "end_reason": o.end_reason, "labels": self.m.labels,
            "final_hp": {"1": a.hp, "2": b.hp}, "max_hp": {"1": a.max_hp, "2": b.max_hp},
            "elapsed_ms": self.m.elapsed_ms, "stats": {"1": dict(a.stats or {}), "2": dict(b.stats or {})},
            "hits_landed": {"1": a.hits_landed, "2": b.hits_landed},
            "damage_dealt": {"1": a.damage_dealt, "2": b.damage_dealt}, "sides": {},
        }
        rewards: dict[int, dict[str, Any]] = {}
        ev = self.emit("match.ended", payload)
        reward_events = {n: self.emit("rewards.granted", {"side": n}, f"p{n}") for n in (1, 2) if not self.side(n).is_bot}
        from app.engine.finish import finish_tx

        def tx(s: Session) -> None:
            finish_tx(s, self.m, o, self.cfg, payload, rewards)
            payload["rewards"] = {str(n): r for n, r in rewards.items()}
            ev.data = payload
            for n, rev in reward_events.items():
                rev.data = {"side": n, **rewards.get(n, {})}
            self.m.result = payload

        self._tx.append(tx)


def _load_events(s: Session, match_id: str, after_seq: int, side: int) -> list[dict[str, Any]]:
    rows = s.exec(
        select(MatchEvent).where(MatchEvent.match_id == match_id, MatchEvent.seq > after_seq).order_by(MatchEvent.seq)  # type: ignore[arg-type]
    ).all()
    return [{"type": r.type, "payload": r.payload, "seq": r.seq} for r in rows if r.visibility in ("both", f"p{side}")]


def _flag(s: Session, match_id: str, profile_id: int, kind: str, details: dict[str, Any]) -> None:
    from app.models import Flag

    s.add(Flag(match_id=match_id, profile_id=profile_id, kind=kind, severity=1, details=details))
