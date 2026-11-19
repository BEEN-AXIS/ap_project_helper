"""The WebSocket protocol, defined once in Pydantic.

`make types` turns these models into frontend/src/net/protocol.generated.ts.
tests/engine/test_protocol.py validates every message a scripted match emits
against EVENT_MODELS, so the generated types describe what is really sent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DamageClass = Literal["light", "heavy", "massive", "nuke"]
Scenario = Literal["heroic", "brave", "ambitious", "stretching", "on_level", "safe", "lazy", "cowardly", "pathetic"]
Verdict = Literal["AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "SE"]


class M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Skins(BaseModel):
    model_config = ConfigDict(extra="allow")
    card: str | None = None
    avatar: str | None = None
    arena: str | None = None
    color: str | None = None
    personality: str | None = None


class PlayerView(M):
    side: int
    profile_id: int
    name: str
    rating: int
    tier: int
    max_hp: int
    hp: int
    skins: Skins
    is_bot: bool
    connected: bool
    hits_landed: int
    damage_dealt: int
    shield_ms_left: int
    judging: bool


class Stage(M):
    theme: str
    owner_side: int | None
    owner_name: str | None


class ClockView(M):
    status: str
    elapsed_ms: int
    server_time_ms: int
    max_ms: int
    bracket: str


class ProblemRef(M):
    slug: str
    title: str
    tier: int
    biome: str
    tags: list[str]


class Preview(M):
    damage: int
    recoil: int
    tier_diff: int
    scenario: Scenario
    crit: bool
    dmg_pct: int
    recoil_pct: int


class Card(M):
    slot: int
    tier: int
    pending: bool
    problem: ProblemRef | None = None
    preview: Preview | None = None
    hints_revealed: int = 0


class Charges(M):
    blocks_left: int
    hints_left: int
    rerolls_left: int
    next_reroll_ms: int


class MatchInfo(M):
    id: str
    mode: str
    map: str
    status: str
    stage: Stage


class Inflight(M):
    submission_id: int | None
    slot: int | None


class RatingStep(M):
    key: str
    delta: int


class Promotion(M):
    from_tier: int
    to_tier: int
    title: str
    old_max_hp: int
    new_max_hp: int
    direction: Literal["up", "down"]


class ProfileAfter(M):
    rating: int
    tier: int
    max_hp: int
    peak_rating: int


class RatingBlock(M):
    before: int
    after: int
    delta: int
    steps: list[RatingStep]
    multiplier: int
    profile_after: ProfileAfter
    raw_delta: int | None = None
    promotion: Promotion | None = None
    practice: bool | None = None


class RewardLine(M):
    key: str
    ap: int


class QuestTick(M):
    id: str
    progress: int
    target: int
    ap: int
    complete: bool


class RewardsGranted(M):
    side: int | None = None
    ap: int = 0
    lines: list[RewardLine] = []
    quests: list[QuestTick] = []
    achievements: list[str] = []
    unlocked: list[str] = []


class MatchEnded(M):
    outcome: Literal["win", "draw", "aborted"]
    winner_side: int | None
    end_reason: str
    labels: dict[str, str]
    final_hp: dict[str, int]
    sides: dict[str, RatingBlock]
    elapsed_ms: int
    reason: str | None = None
    max_hp: dict[str, int] | None = None
    stats: dict[str, dict[str, int | bool | None]] | None = None
    hits_landed: dict[str, int] | None = None
    damage_dealt: dict[str, int] | None = None
    rewards: dict[str, RewardsGranted] | None = None


class StateSnapshot(M):
    match: MatchInfo
    you: int
    players: list[PlayerView]
    clock: ClockView
    hand: list[Card]
    charges: Charges
    hints: dict[str, list[str]]
    cooldown_ms: int
    inflight: Inflight | None
    seq: int
    result: MatchEnded | None


class Countdown(M):
    n: int


class MatchStarted(M):
    players: list[PlayerView]
    mode: str
    map: str
    stage: Stage
    clock: ClockView


class HandUpdated(M):
    cards: list[Card]
    rerolled: int | None = None
    rerolls_left: int | None = None


class CardDealt(M):
    card: Card


class OpponentActivity(M):
    side: int
    state: Literal["arena", "editor", "judging"]


class SubmissionAccepted(M):
    submission_id: int
    slot: int
    problem: str
    total: int
    queue_position: int


class SubmissionProgress(M):
    submission_id: int
    index: int
    code: str
    passed: int
    total: int


class SubmissionVerdict(M):
    submission_id: int | None
    slot: int | None
    verdict: Verdict | None
    void: bool
    failed_test: int | None = None
    passed: int | None = None
    total: int | None = None
    time_ms: int | None = None
    memory_kb: int | None = None
    compile_error: str | None = None
    damage: int | None = None
    recoil: int | None = None
    cooldown_ms: int | None = None
    reason: str | None = None


class AttackLanded(M):
    attacker: int
    defender: int
    damage: int
    damage_class: DamageClass
    crit: bool
    scenario: Scenario
    tier_diff: int
    problem: str
    defender_hp: int
    attacker_damage_dealt: int
    hits_landed: int


class AttackBlocked(M):
    attacker: int
    defender: int
    prevented_damage: int
    damage_class: DamageClass
    crit: bool
    scenario: Scenario
    problem: str
    hits_landed: int


class AttackBackfire(M):
    attacker: int
    recoil: int
    recoil_class: DamageClass
    verdict: Verdict
    problem: str
    attacker_hp: int
    crit: bool
    scenario: Scenario


class PowerupUsed(M):
    side: int
    kind: Literal["block", "hint"]
    charges_left: int
    shield_ms: int | None = None


class HintRevealed(M):
    slot: int
    problem: str
    level: int
    text: str
    tags: list[str] | None = None


class SideOnly(M):
    side: int


class PlayerDisconnected(M):
    side: int
    grace_s: int


class Emote(M):
    side: int
    id: str


class SessionMoved(M):
    reason: str
    message: str | None = None


class Pong(M):
    id: int | str | None
    server_time_ms: int | None = None


EVENT_MODELS: dict[str, type[BaseModel]] = {
    "state.snapshot": StateSnapshot,
    "match.countdown": Countdown,
    "match.started": MatchStarted,
    "hand.updated": HandUpdated,
    "card.dealt": CardDealt,
    "opponent.activity": OpponentActivity,
    "submission.accepted": SubmissionAccepted,
    "submission.progress": SubmissionProgress,
    "submission.verdict": SubmissionVerdict,
    "attack.landed": AttackLanded,
    "attack.blocked": AttackBlocked,
    "attack.backfire": AttackBackfire,
    "powerup.used": PowerupUsed,
    "hint.revealed": HintRevealed,
    "shield.expired": SideOnly,
    "player.disconnected": PlayerDisconnected,
    "player.reconnected": SideOnly,
    "match.timer": ClockView,
    "emote": Emote,
    "match.ended": MatchEnded,
    "rewards.granted": RewardsGranted,
    "session.moved": SessionMoved,
    "pong": Pong,
}
