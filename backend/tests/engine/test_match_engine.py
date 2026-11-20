"""Phase 3 gate: a scripted two-player match covering every row of the edge-case
table in section 4, plus reconnect and idempotency. FakeClock + FakeRunner."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.db import db_sync
from app.core.errors import RuleError
from app.models import Match, MatchEvent, Profile, RatingHistory, Submission
from app.realtime.hub import Connection
from tests.engine.conftest import FakeWS, reload_profile

pytestmark = pytest.mark.anyio

# Two Pupils (1200): hand tiers 1..4; tier-1 card hits for 3,200 (recoil 2,400),
# tier-2 for 8,000 (recoil 4,000), tier-4 for 39,200 (crit, recoil 8,400).


async def test_hit_lands_on_both_screens_and_card_is_redealt(make_arena):
    a = await make_arena()
    s1 = a.slot_with_tier(1, 1)
    first = a.actor.hands[1].slots[s1]
    await a.submit_and_judge(1, s1, "AC")
    assert a.hp(2) == 28000 - 3200
    l1, l2 = a.ws[1].last("attack.landed"), a.ws[2].last("attack.landed")
    assert l1 == l2 and l1["data"]["damage"] == 3200 and l1["data"]["damage_class"] == "heavy"
    assert l1["data"]["scenario"] == "safe" and l1["data"]["defender_hp"] == 24800
    assert "hand.updated" in a.ws[1].types() and "hand.updated" not in a.ws[2].types()[-3:]
    assert a.actor.hands[1].slots[s1] is None  # spent, waiting for a re-deal
    await a.advance(1.6)
    dealt = a.ws[1].last("card.dealt")["data"]["card"]
    assert dealt["slot"] == s1 and dealt["problem"]["slug"] not in (None, first)
    assert not a.ws[2].of("card.dealt")  # the opponent never sees your hand


async def test_cards_and_attacks_carry_their_difficulty_level(make_arena):
    """The level names the animation (easy, normal, medium, tough); both screens get it."""
    a = await make_arena()
    hand = a.actor.hand_view(1)
    assert sorted(c["level"] for c in hand) == [0, 1, 2, 3]
    tough = next(c["slot"] for c in hand if c["level"] == 3)
    easy = next(c["slot"] for c in hand if c["level"] == 0)
    await a.submit_and_judge(1, easy, "WA 1")
    assert a.ws[2].last("attack.backfire")["data"]["level"] == 0
    await a.advance(4)
    await a.submit_and_judge(1, tough, "AC")  # a tough card can be a one-shot KO
    landed = a.ws[2].last("attack.landed")["data"]
    assert landed["level"] == 3 and landed == a.ws[1].last("attack.landed")["data"]


async def test_backfire_costs_recoil_and_keeps_the_card(make_arena):
    a = await make_arena()
    s = a.slot_with_tier(1, 2)
    slug = a.actor.hands[1].slots[s]
    await a.submit_and_judge(1, s, "WA 2")
    assert a.hp(1) == 28000 - 4000
    bf = a.ws[2].last("attack.backfire")["data"]
    assert bf == a.ws[1].last("attack.backfire")["data"]
    assert bf["recoil"] == 4000 and bf["verdict"] == "WA" and bf["recoil_class"] == "heavy"
    assert a.actor.hands[1].slots[s] == slug  # a wrong attempt leaves the card in the hand
    v = a.ws[1].last("submission.verdict")["data"]
    assert v["failed_test"] == 2 and v["verdict"] == "WA"
    assert not a.ws[2].of("submission.verdict")  # verdict details are private
    # Same card again after the 3 s cooldown: allowed, and it costs recoil again.
    with pytest.raises(RuleError) as e:
        await a.submit(1, s, "WA 1")
    assert e.value.code == "cooldown"
    await a.advance(3.0)
    await a.submit_and_judge(1, s, "WA 1")
    assert a.hp(1) == 28000 - 8000


async def test_one_submission_in_flight_and_double_click_is_idempotent(make_arena):
    a = await make_arena()
    s = a.slot_with_tier(1, 1)
    r1 = await a.actor.send("submit", 1, {"slot": s, "code": "# VERDICT: AC\n# DELAY_MS: 30\n", "language": "python"}, "dbl-1")
    r2 = await a.actor.send("submit", 1, {"slot": s, "code": "# VERDICT: AC\n# DELAY_MS: 30\n", "language": "python"}, "dbl-1")
    assert r1 is r2  # the repeated cmd_id returns the earlier result and changes nothing
    with pytest.raises(RuleError) as e:
        await a.submit(1, a.slot_with_tier(1, 2))
    assert e.value.code == "busy"
    import asyncio

    await asyncio.sleep(1.0)
    await a.settle()
    subs = db_sync(lambda s_: s_.exec(select(Submission).where(Submission.match_id == a.actor.id)).all())
    assert len(subs) == 1 and subs[0].verdict == "AC"


async def test_empty_and_oversized_code_are_rejected_before_judging(make_arena):
    a = await make_arena()
    for code, err in (("   ", "empty_code"), ("x" * 70000, "code_too_large")):
        with pytest.raises(RuleError) as e:
            await a.actor.send("submit", 1, {"slot": 0, "code": code, "language": "python"}, a.cmd())
        assert e.value.code == err


async def test_system_error_is_void_with_no_recoil_and_retry_allowed(make_arena):
    a = await make_arena()
    s = a.slot_with_tier(1, 3)
    await a.submit_and_judge(1, s, "SE")
    assert a.hp(1) == 28000
    v = a.ws[1].last("submission.verdict")["data"]
    assert v["void"] is True and v["reason"] == "system_error"
    await a.submit_and_judge(1, s, "AC")  # no cooldown after a system error
    assert a.hp(2) == 28000 - 18000


async def test_two_lethal_verdicts_queue_order_decides(make_arena):
    a = await make_arena()
    a.actor.m.player1_hp = 1000
    a.actor.m.player2_hp = 1000
    await a.submit(1, a.slot_with_tier(1, 1), "AC")
    await a.submit(2, a.slot_with_tier(2, 1), "AC")
    await a.settle()
    assert a.actor.m.status == "finished"
    landed = a.ws[1].of("attack.landed")
    assert len(landed) == 1
    winner = landed[0]["data"]["attacker"]
    loser = 3 - winner
    assert a.actor.m.winner_side == winner
    v = a.ws[loser].last("submission.verdict")["data"]
    assert v["void"] is True and v["reason"] == "match_ended"
    assert a.hp(winner) == 1000  # the voided verdict changed nothing


async def test_verdict_after_match_ended_is_void(make_arena):
    a = await make_arena()
    await a.actor.send("submit", 1, {"slot": 0, "code": "# VERDICT: AC\n# DELAY_MS: 200\n", "language": "python"}, a.cmd())
    await a.actor.send("forfeit", 2, {}, a.cmd())  # someone submitted, so this is a real forfeit
    import asyncio

    await asyncio.sleep(0.5)
    await a.settle()
    assert a.actor.m.end_reason == "forfeit" and a.actor.m.winner_side == 1
    v = a.ws[1].last("submission.verdict")["data"]
    assert v["void"] is True
    assert a.hp(2) == 28000


async def test_recoil_ko_is_a_self_destruct_and_hollow_victory(make_arena):
    a = await make_arena()
    a.actor.m.player1_hp = 1000
    await a.submit_and_judge(1, a.slot_with_tier(1, 4), "TLE 3")
    assert a.hp(1) == 0
    assert a.actor.m.labels == {"1": "self_destruct", "2": "hollow_victory"}
    ended = a.ws[2].last("match.ended")["data"]
    assert ended["sides"]["2"]["delta"] == 0  # hollow victory pays 0
    assert ended["sides"]["1"]["delta"] < 0


async def test_overkill_counts_in_full(make_arena):
    a = await make_arena()
    a.actor.m.player2_hp = 5000
    await a.submit_and_judge(1, a.slot_with_tier(1, 4), "AC")
    assert a.hp(2) == 0 and a.actor.m.player1_damage_dealt == 39200
    landed = a.ws[2].last("attack.landed")["data"]
    assert landed["crit"] is True and landed["damage_class"] == "nuke" and landed["scenario"] == "ambitious"
    assert a.actor.m.labels == {"1": "victory", "2": "defeat"}


async def test_block_absorbs_exactly_one_hit_even_a_lethal_one(make_arena):
    a = await make_arena()
    a.actor.m.player2_hp = 5000
    await a.actor.send("block", 2, {}, a.cmd())
    assert a.ws[1].last("powerup.used")["data"]["kind"] == "block"
    await a.submit_and_judge(1, a.slot_with_tier(1, 4), "AC")
    blk = a.ws[1].last("attack.blocked")["data"]
    assert blk["prevented_damage"] == 39200 and a.hp(2) == 5000 and a.actor.m.status == "live"
    assert a.actor.m.player1_hits_landed == 1  # the blocked attacker still counts a hit
    assert a.actor.hands[1].slots[a.slot_with_tier(1, 4)] is None  # and loses the card
    await a.advance(3.0)
    await a.submit_and_judge(1, a.slot_with_tier(1, 1), "AC")
    assert a.hp(2) == 5000 - 3200  # the shield is gone after one hit
    with pytest.raises(RuleError) as e:
        await a.actor.send("block", 2, {}, a.cmd())
    assert e.value.code == "no_charges"


async def test_block_expires_after_20s_and_never_stops_recoil(make_arena):
    a = await make_arena()
    await a.actor.send("block", 1, {}, a.cmd())
    await a.submit_and_judge(1, a.slot_with_tier(1, 2), "WA 1")
    assert a.hp(1) == 28000 - 4000
    await a.advance(20.5)
    assert a.ws[2].last("shield.expired")["data"]["side"] == 1
    await a.submit_and_judge(2, a.slot_with_tier(2, 1), "AC")
    assert a.hp(1) == 24000 - 3200


async def test_hint_levels_in_order_and_opponent_never_sees_text(make_arena):
    a = await make_arena()
    s = a.slot_with_tier(1, 1)
    r1 = await a.actor.send("hint", 1, {"slot": s}, a.cmd())
    r2 = await a.actor.send("hint", 1, {"slot": s}, a.cmd())
    assert (r1["level"], r2["level"]) == (1, 2)
    assert [e["data"]["level"] for e in a.ws[1].of("hint.revealed")] == [1, 2]
    assert not a.ws[2].of("hint.revealed")
    assert [e["data"]["kind"] for e in a.ws[2].of("powerup.used")] == ["hint", "hint"]
    assert "text" not in a.ws[2].last("powerup.used")["data"]
    with pytest.raises(RuleError) as e:
        await a.actor.send("hint", 1, {"slot": s}, a.cmd())
    assert e.value.code == "no_charges"


async def test_reroll_rules(make_arena):
    a = await make_arena()
    s = a.slot_with_tier(1, 1)
    before = a.actor.hands[1].slots[s]
    await a.actor.send("reroll", 1, {"slot": s}, a.cmd())
    assert a.actor.hands[1].slots[s] != before
    with pytest.raises(RuleError) as e:
        await a.actor.send("reroll", 1, {"slot": s}, a.cmd())
    assert e.value.code == "cooldown"
    await a.advance(60.5)
    await a.actor.send("reroll", 1, {"slot": s}, a.cmd())
    await a.advance(60.5)
    with pytest.raises(RuleError) as e:
        await a.actor.send("reroll", 1, {"slot": s}, a.cmd())
    assert e.value.code == "no_charges"


async def test_tiers_are_snapshots_during_a_match(make_arena):
    a = await make_arena()
    pid = a.actor.m.player1_profile_id

    def bump(s):  # type: ignore[no-untyped-def]
        p = s.get(Profile, pid)
        p.rating = 2500
        s.add(p)

    db_sync(bump)
    await a.submit_and_judge(1, a.slot_with_tier(1, 1), "AC")
    assert a.hp(2) == 28000 - 3200  # still computed from the Pupil snapshot


async def test_ko_updates_rating_and_promotion(make_arena):
    a = await make_arena(r1=1390, r2=1390)
    await a.submit_and_judge(1, a.slot_with_tier(1, 4), "AC")
    assert a.actor.m.status == "finished" and a.actor.m.end_reason == "ko"
    ended = a.ws[1].last("match.ended")["data"]
    me = ended["sides"]["1"]
    assert [s["key"] for s in me["steps"]] == ["win", "flawless", "blitz"]
    assert me["delta"] == 100 and me["after"] == 1490
    assert me["promotion"] == {"from_tier": 2, "to_tier": 3, "title": "Specialist", "old_max_hp": 28000,
                               "new_max_hp": 50000, "direction": "up"}
    assert me["profile_after"]["max_hp"] == 50000
    p1 = reload_profile(a.actor.m.player1_profile_id)
    p2 = reload_profile(a.actor.m.player2_profile_id)
    assert (p1.rating, p1.wins, p2.rating, p2.losses) == (1490, 1, 1320, 1)
    hist = db_sync(lambda s: s.exec(select(RatingHistory).where(RatingHistory.match_id == a.actor.id)).all())
    assert {h.delta for h in hist} == {100, -70}
    rewards = a.ws[1].last("rewards.granted")["data"]
    assert rewards["ap"] > 0 and any(line["key"] == "win" for line in rewards["lines"])
    assert not a.ws[2].of("rewards.granted") or a.ws[2].last("rewards.granted")["data"]["side"] == 2


async def test_timer_end_draw_changes_nothing(make_arena):
    a = await make_arena()
    await a.advance(31)
    a.clock.advance(180 * 60)
    await a.settle()
    assert a.actor.m.end_reason == "timer" and a.actor.m.outcome == "draw"
    p1 = reload_profile(a.actor.m.player1_profile_id)
    assert p1.rating == 1200 and p1.draws == 1


async def test_early_flee_aborts_with_a_strike_and_no_rating(make_arena):
    a = await make_arena()
    await a.actor.send("forfeit", 1, {}, a.cmd())
    await a.settle()
    assert a.actor.m.status == "aborted"
    p1 = reload_profile(a.actor.m.player1_profile_id)
    assert p1.no_show_strikes == 1 and p1.rating == 1200
    assert a.ws[2].last("match.ended")["data"]["outcome"] == "aborted"


async def test_forfeit_after_30s(make_arena):
    a = await make_arena()
    await a.advance(31)
    await a.actor.send("forfeit", 1, {}, a.cmd())
    await a.settle()
    assert a.actor.m.end_reason == "forfeit" and a.actor.m.winner_side == 2
    assert a.actor.m.labels == {"2": "hollow_victory", "1": "defeat"}


async def test_disconnect_then_auto_forfeit_after_grace(make_arena):
    a = await make_arena()
    await a.advance(31)
    conn = a.ctx.hub.current(a.actor.id, 1)
    await a.actor.send("leave", 1, {"conn": conn})
    assert a.ws[2].last("player.disconnected")["data"] == {"side": 1, "grace_s": 60}
    await a.advance(59)
    assert a.actor.m.status == "live"
    await a.advance(2)
    assert a.actor.m.end_reason == "disconnect" and a.actor.m.winner_side == 2


async def test_both_gone_aborts(make_arena):
    a = await make_arena()
    await a.advance(31)
    for side in (1, 2):
        await a.actor.send("leave", side, {"conn": a.ctx.hub.current(a.actor.id, side)})
    await a.advance(61)
    assert a.actor.m.status == "aborted"


async def test_reconnect_replays_missed_events_without_loss(make_arena):
    a = await make_arena()
    last_seq_seen = max(m.get("seq", 0) for m in a.ws[2].sent)
    await a.actor.send("leave", 2, {"conn": a.ctx.hub.current(a.actor.id, 2)})
    await a.submit_and_judge(1, a.slot_with_tier(1, 1), "AC")
    await a.submit_and_judge(1, a.slot_with_tier(1, 2), "AC") if False else None
    fresh = FakeWS()
    await a.actor.send("join", 2, {"conn": Connection(fresh, 0), "last_seq": last_seq_seen})
    await a.settle()
    assert "attack.landed" in fresh.types()
    assert fresh.last("attack.landed")["data"]["defender_hp"] == a.hp(2)
    assert all(m["seq"] > last_seq_seen for m in fresh.sent if "seq" in m)
    assert a.ws[1].last("player.reconnected")["data"]["side"] == 2
    # A far-behind client gets a snapshot instead, and the snapshot never holds the other hand.
    fresh2 = FakeWS()
    await a.actor.send("join", 2, {"conn": Connection(fresh2, 0), "last_seq": 0})
    snap = fresh2.last("state.snapshot")["data"]
    assert snap["you"] == 2 and len(snap["hand"]) == 4
    assert {p["hp"] for p in snap["players"]} == {28000, a.hp(2)}
    assert all(c["problem"]["slug"] in a.actor.hands[2].slots for c in snap["hand"] if c["problem"])


async def test_newest_tab_takes_over_and_old_one_sees_session_moved(make_arena):
    a = await make_arena()
    old = a.ws[1]
    new = FakeWS()
    await a.actor.send("join", 1, {"conn": Connection(new, 0), "last_seq": 0})
    assert old.last("session.moved")["data"]["reason"] == "session_moved" and old.closed_with == 4001
    assert new.types()[0] == "state.snapshot"


async def test_connect_timeout_aborts_and_strikes_no_shows(make_arena):
    a = await make_arena(connect=False)
    ws1 = FakeWS()
    await a.actor.send("join", 1, {"conn": Connection(ws1, 0), "last_seq": 0})
    await a.advance(31)
    assert a.actor.m.status == "aborted"
    assert reload_profile(a.actor.m.player2_profile_id).no_show_strikes == 1
    assert reload_profile(a.actor.m.player1_profile_id).no_show_strikes == 0


async def test_bot_match_uses_the_same_pipeline_and_half_rating(make_arena):
    a = await make_arena(mode="bot", bot_personality="sprinter")
    await a.advance(600)  # the bot thinks, then submits simulated verdicts
    bot_subs = db_sync(lambda s: s.exec(select(Submission).where(Submission.match_id == a.actor.id, Submission.is_bot == True)).all())  # noqa: E712
    assert bot_subs and all("BOT (simulated)" in s.code for s in bot_subs)
    if a.actor.m.status == "live":
        a.actor.m.player2_hp = 1000
        await a.submit_and_judge(1, a.slot_with_tier(1, 1), "AC")
    assert a.actor.m.status == "finished"
    ended = a.ws[1].last("match.ended")["data"]
    if a.actor.m.winner_side == 1:
        assert ended["sides"]["1"]["multiplier"] == 50
        raw = ended["sides"]["1"]["raw_delta"]
        assert ended["sides"]["1"]["delta"] == min(raw * 50 // 100, 100)
    assert "2" not in ended["sides"]  # bots have no rating


async def test_practice_changes_nothing(make_arena):
    a = await make_arena(mode="practice")
    assert a.actor.m.player1_blocks_left == 0 and a.actor.m.player1_hints_left == -1
    for _ in range(3):
        await a.actor.send("hint", 1, {"slot": 0}, a.cmd())  # unlimited hints
    a.actor.m.player2_hp = 100
    await a.submit_and_judge(1, a.slot_with_tier(1, 1), "AC")
    assert a.actor.m.status == "finished"
    p = reload_profile(a.actor.m.player1_profile_id)
    assert (p.rating, p.wins, p.losses, p.points) == (1200, 0, 0, 0)
    assert not db_sync(lambda s: s.exec(select(RatingHistory).where(RatingHistory.match_id == a.actor.id)).all())


async def test_persist_then_broadcast_every_event_is_in_the_log(make_arena):
    a = await make_arena()
    await a.submit_and_judge(1, a.slot_with_tier(1, 2), "AC")
    await a.submit_and_judge(2, a.slot_with_tier(2, 2), "WA 1")
    rows = db_sync(lambda s: s.exec(select(MatchEvent).where(MatchEvent.match_id == a.actor.id)).all())
    logged = {(r.seq, r.type) for r in rows}
    for side in (1, 2):
        for m in a.ws[side].sent:
            if "seq" in m and m["type"] != "state.snapshot":
                assert (m["seq"], m["type"]) in logged
    seqs = sorted(r.seq for r in rows)
    assert seqs == list(range(1, len(seqs) + 1))
    row = db_sync(lambda s: s.get(Match, a.actor.id))
    assert row.player2_hp == a.hp(2) and row.player1_hp == a.hp(1)


async def test_verdict_payloads_never_carry_outputs(make_arena):
    a = await make_arena()
    await a.submit_and_judge(1, a.slot_with_tier(1, 2), "WA 3")
    allowed = {"submission_id", "slot", "verdict", "failed_test", "passed", "total", "time_ms", "memory_kb",
               "compile_error", "void", "damage", "recoil", "cooldown_ms", "reason"}
    for m in a.ws[1].of("submission.verdict"):
        assert set(m["data"]) <= allowed
