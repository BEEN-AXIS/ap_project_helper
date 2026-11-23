"""API: auth flows, rate limits, authorization, and a full queue -> match over
real WebSockets (TestClient, ENV=test, FakeRunner)."""

from __future__ import annotations

import itertools
import time

import pytest
from fastapi.testclient import TestClient

from app.core.ratelimit import limiter
from app.main import create_app
from tests.engine.conftest import ensure_seeded

_n = itertools.count()


@pytest.fixture(scope="module")
def client():  # type: ignore[no-untyped-def]
    ensure_seeded()
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_limits():  # type: ignore[no-untyped-def]
    limiter.reset()
    yield


def signup(c: TestClient, name: str | None = None) -> tuple[str, dict]:
    name = name or f"user{next(_n)}_{int(time.time()) % 10000}"
    limiter.reset()
    r = c.post("/api/auth/signup", json={"username": name, "password": f"{name}-pass-9"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], r.json()["profile"]


def H(tok: str) -> dict:
    return {"authorization": f"Bearer {tok}"}


def test_signup_validation_and_starting_profile(client: TestClient) -> None:
    bad = client.post("/api/auth/signup", json={"username": "x", "password": "longenough1"})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "username"
    limiter.reset()
    weak = client.post("/api/auth/signup", json={"username": "weakling", "password": "password"})
    assert weak.json()["error"]["code"] == "validation"
    limiter.reset()
    extra = client.post("/api/auth/signup", json={"username": "cheater1", "password": "cheater-pass", "rating": 3000})
    assert extra.status_code == 422  # unknown fields are rejected: no client-set rating
    tok, prof = signup(client)
    assert (prof["rating"], prof["tier"], prof["max_hp"]) == (1200, 2, 28000)
    limiter.reset()
    dup = client.post("/api/auth/signup", json={"username": prof["display_name"].upper(), "password": "another-pass"})
    assert dup.json()["error"]["code"] == "conflict"  # unique ignoring case


def test_login_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    name = f"rot{next(_n)}"
    signup(client, name)
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": name, "password": "nope-nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": name, "password": f"{name}-pass-9"})
    assert r.status_code == 200
    first = client.cookies.get("aa_refresh")
    r2 = client.post("/api/auth/refresh")
    assert r2.status_code == 200 and client.cookies.get("aa_refresh") != first
    # Replaying the old, rotated token revokes the whole session family.
    client.cookies.set("aa_refresh", first, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    client.cookies.clear()


def test_rate_limits_return_429_with_retry_after(client: TestClient) -> None:
    codes = [client.post("/api/auth/login", json={"username": "ghost", "password": "whatever1"}).status_code for _ in range(7)]
    assert codes.count(429) >= 1
    r = client.post("/api/auth/login", json={"username": "ghost", "password": "whatever1"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"


def test_no_route_accepts_a_rating_hp_or_result(client: TestClient) -> None:
    tok, prof = signup(client)
    for method, path in (("PUT", f"/api/players/{prof['id']}?new_elo=3000"), ("DELETE", "/api/match/1/end"),
                         ("PUT", "/api/battle/1/attacker/1/problem/1"), ("POST", "/api/players/")):
        assert client.request(method, path, headers=H(tok)).status_code in (404, 405)
    assert client.patch("/api/me/settings", headers=H(tok), json={"rating": 3000}).status_code == 422


def test_config_and_health_are_public(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert cfg["game_name"] == "AlgoArena" and "bots" not in cfg and "rate_limits" not in cfg
    assert client.get("/api/healthz").json()["database"] is True


def test_cannot_act_in_someone_elses_match_or_read_their_drafts(client: TestClient) -> None:
    ta, _ = signup(client)
    tb, _ = signup(client)
    mid = client.post("/api/matches/practice", headers=H(ta), json={"map": "bit"}).json()["match_id"]
    r = client.post(f"/api/matches/{mid}/submit", headers=H(tb), json={"slot": 0, "code": "print(1)", "cmd_id": "abcd"})
    assert r.status_code == 403
    assert client.get(f"/api/matches/{mid}/drafts", headers=H(tb)).json()["drafts"] == []
    assert client.put(f"/api/matches/{mid}/drafts/0", headers=H(tb), json={"code": "x"}).status_code == 403
    assert client.post("/api/auth/ws-ticket", headers=H(tb), json={"scope": "match", "match_id": mid}).status_code == 403
    client.post(f"/api/matches/{mid}/forfeit", headers=H(ta), json={"cmd_id": "flee-1"})


def _ws_until(ws, type_: str, limit: int = 60) -> dict:  # type: ignore[no-untyped-def]
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"never saw {type_}")


def test_two_players_queue_ready_check_and_fight(client: TestClient) -> None:
    ta, pa = signup(client)
    tb, pb = signup(client)
    ticket_a = client.post("/api/auth/ws-ticket", headers=H(ta), json={"scope": "lobby"}).json()["ticket"]
    ticket_b = client.post("/api/auth/ws-ticket", headers=H(tb), json={"scope": "lobby"}).json()["ticket"]
    with client.websocket_connect(f"/ws/lobby?ticket={ticket_a}") as la, client.websocket_connect(f"/ws/lobby?ticket={ticket_b}") as lb:
        assert la.receive_json()["type"] == "hello"
        assert client.post("/api/queue/join", headers=H(ta), json={"map": "bit"}).json()["state"] == "queued"
        assert client.post("/api/queue/join", headers=H(tb), json={"map": "any"}).json()["state"] == "queued"
        found_a = _ws_until(la, "match.found")["data"]
        found_b = _ws_until(lb, "match.found")["data"]
        assert found_a["proposal_id"] == found_b["proposal_id"] and found_a["map"] == "bit"
        assert found_a["opponent"]["name"] == pb["display_name"]
        assert client.post("/api/queue/respond", headers=H(ta), json={"proposal_id": found_a["proposal_id"], "accept": True}).json()["state"] == "waiting"
        ready = client.post("/api/queue/respond", headers=H(tb), json={"proposal_id": found_a["proposal_id"], "accept": True}).json()
        mid = ready["match_id"]
        assert _ws_until(la, "match.ready")["data"]["match_id"] == mid

    ma = client.post("/api/auth/ws-ticket", headers=H(ta), json={"scope": "match", "match_id": mid}).json()["ticket"]
    mb = client.post("/api/auth/ws-ticket", headers=H(tb), json={"scope": "match", "match_id": mid}).json()["ticket"]
    with client.websocket_connect(f"/ws/match/{mid}?ticket={ma}") as wa, client.websocket_connect(f"/ws/match/{mid}?ticket={mb}") as wb:
        wa.send_json({"v": 1, "type": "hello", "data": {"last_seq": 0}})
        snap = _ws_until(wa, "state.snapshot")["data"]
        assert snap["you"] == 1 and snap["match"]["status"] == "starting"
        wb.send_json({"v": 1, "type": "hello", "data": {"last_seq": 0}})
        assert _ws_until(wa, "match.countdown")["data"]["n"] == 3
        started = _ws_until(wa, "match.started", 200)["data"]
        assert [p["name"] for p in started["players"]] == [pa["display_name"], pb["display_name"]]
        hand = _ws_until(wa, "hand.updated")["data"]["cards"]
        slot = next(c["slot"] for c in hand if c["tier"] == 4)
        assert hand[slot]["preview"]["damage"] == 39200 and hand[slot]["preview"]["crit"] is True

        wa.send_json({"v": 1, "type": "ping", "data": {"id": 7}})
        assert _ws_until(wa, "pong")["data"]["id"] == 7

        r = client.post(f"/api/matches/{mid}/run", headers=H(ta), json={"slot": slot, "code": "# VERDICT: WA 1\nprint(0)"})
        assert r.status_code == 200 and r.json()["mode"] == "samples"
        body = {"slot": slot, "code": "# VERDICT: AC\n# DELAY_MS: 5\nprint(1)", "cmd_id": "attack-1"}
        r1 = client.post(f"/api/matches/{mid}/submit", headers=H(ta), json=body)
        r2 = client.post(f"/api/matches/{mid}/submit", headers=H(ta), json=body)  # double click
        assert r1.status_code == 202 and r1.json() == r2.json()
        assert _ws_until(wb, "opponent.activity")["data"]["state"] == "judging"
        landed_b = _ws_until(wb, "attack.landed")["data"]
        landed_a = _ws_until(wa, "attack.landed")["data"]
        assert landed_a == landed_b and landed_a["defender_hp"] == 0 and landed_a["damage_class"] == "nuke"
        ended = _ws_until(wb, "match.ended")["data"]
        assert ended["outcome"] == "win" and ended["winner_side"] == 1 and ended["labels"] == {"1": "victory", "2": "defeat"}
        assert ended["sides"]["1"]["delta"] > 0 and ended["sides"]["2"]["delta"] < 0
        rewards = _ws_until(wa, "rewards.granted")["data"]
        assert rewards["ap"] >= 30

    me = client.get("/api/me", headers=H(ta)).json()
    assert me["rating"] == 1200 + ended["sides"]["1"]["delta"] and me["wins"] == 1 and me["active_match"] is None
    summary = client.get(f"/api/matches/{mid}", headers=H(tb)).json()
    assert summary["result"]["outcome"] == "win"
    events = client.get(f"/api/matches/{mid}/events", headers=H(tb)).json()["events"]
    kinds = [e["type"] for e in events]
    assert "attack.landed" in kinds and "hand.updated" not in kinds and "submission.verdict" not in kinds


def _boards_the_old_way(scope: str, map_: str | None) -> list[tuple[int, int]]:
    """The leaderboard as the app used to build it: every person loaded and ranked
    in Python. The indexed queries must give the same (profile_id, score) order."""
    from datetime import timedelta

    from sqlmodel import select

    from app.core.db import session
    from app.models import Match, Profile, utcnow

    with session() as s:
        profs = {p.id: p for p in s.exec(select(Profile).where(Profile.is_bot == False, Profile.user_id != None)).all()}  # noqa: E711, E712
        score: dict[int, int] = {}
        if scope == "all" and not map_:
            score = {pid: p.rating for pid, p in profs.items()}  # type: ignore[misc]
        else:
            q = select(Match).where(Match.status == "finished")
            if scope == "week":
                q = q.where(Match.end_time >= utcnow() - timedelta(days=7))  # type: ignore[operator]
            if map_:
                q = q.where(Match.map == map_)
            for m in s.exec(q).all():
                if map_:
                    wid = m.player1_profile_id if m.winner_side == 1 else m.player2_profile_id
                    if m.winner_side and wid in profs:
                        score[wid] = score.get(wid, 0) + 1
                else:
                    for n, pid in (("1", m.player1_profile_id), ("2", m.player2_profile_id)):
                        blk = (m.result or {}).get("sides", {}).get(n)
                        if blk and pid in profs:
                            score[pid] = score.get(pid, 0) + int(blk.get("delta", 0))
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], profs[kv[0]].display_name.lower()))
    return [(pid, sc) for pid, sc in ranked]


def test_leaderboards_read_through_indexes_rank_like_before(client: TestClient) -> None:
    import uuid

    from app.core.db import session
    from app.models import Match, Profile, User, utcnow

    tok, me = signup(client, f"mid{next(_n)}")
    # 120 people rated above the default 1200, then ten tied at 1200: seven named before "mid…", three after
    with session() as s:
        made = []
        for i in range(130):
            name = f"lb{next(_n)}_{i}" if i < 120 else (f"zz{next(_n)}" if i % 4 == 0 else f"aa{next(_n)}")
            u = User(username=name, username_lower=name.lower(), password_hash="x")
            s.add(u)
            s.flush()
            p = Profile(user_id=u.id, display_name=name, rating=1300 + (i * 7) % 400 if i < 120 else 1200)
            s.add(p)
            s.flush()
            made.append(p.id)
        for k in range(12):   # finished matches this week, with rating changes and winners on two maps
            a, b = made[k], made[k + 1]
            s.add(Match(id=str(uuid.uuid4()), mode="ranked", map="bit" if k % 3 else "prestige", status="finished", seed=k,
                        end_time=utcnow(), winner_side=1 + k % 2, outcome="win", player1_profile_id=a, player2_profile_id=b,
                        result={"sides": {"1": {"delta": 10 + k}, "2": {"delta": -8 - k}}}))
        s.commit()

    client.app.state.ctx.cache.clear()  # type: ignore[attr-defined]
    for scope, map_ in (("all", None), ("week", None), ("all", "bit"), ("week", "prestige")):
        params = {"scope": scope, **({"map": map_} if map_ else {})}
        got = client.get("/api/leaderboard", params=params, headers=H(tok)).json()
        want = _boards_the_old_way(scope, map_)
        assert [(r["profile_id"], r["score"]) for r in got["rows"]] == want[:100], (scope, map_)
        assert [r["rank"] for r in got["rows"]] == list(range(1, len(got["rows"]) + 1))
        mine = next((i for i, (pid, _) in enumerate(want, 1) if pid == me["id"]), None)
        assert (got["me"] or {}).get("rank") == mine, (scope, map_)
    # outside the top 100 on the all-time board, "me" comes from a count, not the list
    allt = client.get("/api/leaderboard", headers=H(tok)).json()
    assert allt["me"]["rank"] > 100 and allt["me"]["profile_id"] == me["id"]
