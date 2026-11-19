"""Every message a scripted match sends must validate against the protocol models
that the TypeScript types are generated from."""

from __future__ import annotations

import pytest

from app.realtime.protocol import EVENT_MODELS

pytestmark = pytest.mark.anyio


async def test_every_emitted_message_matches_the_protocol(make_arena):
    a = await make_arena(r1=1300, r2=1250)
    await a.actor.send("hint", 1, {"slot": 0}, a.cmd())
    await a.actor.send("block", 2, {}, a.cmd())
    await a.submit_and_judge(1, a.slot_with_tier(1, 2), "AC")       # blocked
    await a.submit_and_judge(2, a.slot_with_tier(2, 1), "WA 2")     # backfire
    await a.actor.send("emote", 1, {"id": "gg"}, a.cmd())
    await a.advance(20)
    await a.actor.send("reroll", 2, {"slot": 0}, a.cmd())
    await a.submit_and_judge(1, a.slot_with_tier(1, 4), "AC")       # KO
    seen: set[str] = set()
    for side in (1, 2):
        for m in a.ws[side].sent:
            model = EVENT_MODELS.get(m["type"])
            assert model is not None, f"no protocol model for {m['type']}"
            model.model_validate(m["data"])
            seen.add(m["type"])
    for must in ("state.snapshot", "match.started", "hand.updated", "card.dealt", "attack.blocked", "attack.backfire",
                 "attack.landed", "powerup.used", "hint.revealed", "match.ended", "rewards.granted", "emote",
                 "submission.verdict", "submission.accepted", "opponent.activity", "match.timer"):
        assert must in seen, must
