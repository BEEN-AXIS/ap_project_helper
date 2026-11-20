"""SQLModel tables. Importing this package registers every table."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def JsonCol(default=None):  # type: ignore[no-untyped-def]  # noqa: N802
    return Field(default_factory=(lambda: default() if callable(default) else default), sa_column=Column(JSON))


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(max_length=20)
    username_lower: str = Field(max_length=20, unique=True, index=True)
    password_hash: str
    role: str = Field(default="player", max_length=16)
    suspended_until: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(unique=True, index=True, max_length=64)
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Profile(SQLModel, table=True):
    """The chat's Player table, renamed. Tier and max HP are derived from rating."""

    __tablename__ = "profiles"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", unique=True)
    display_name: str = Field(max_length=32, index=True)
    rating: int = 1200
    peak_rating: int = 1200
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: int = 0
    equipped_card: str = Field(default="card.classic", max_length=48)
    equipped_avatar: str = Field(default="bean.plain", max_length=48)
    equipped_arena: str | None = Field(default=None, max_length=48)
    equipped_weapon: str = Field(default="weapon.fireball", max_length=48)
    avatar_color: str = Field(default="#3b82f6", max_length=9)
    settings: dict = JsonCol(dict)  # type: ignore[type-arg]
    is_bot: bool = False
    personality: str | None = Field(default=None, max_length=16)
    bot_gain_today: int = 0
    casual_ap_today: int = 0
    daily_day: str = Field(default="", max_length=10)  # UTC date the two counters above belong to
    last_win_day: str = Field(default="", max_length=10)
    no_show_strikes: int = 0
    queue_ban_until: datetime | None = None
    counters: dict = JsonCol(dict)  # type: ignore[type-arg]
    badges: list = JsonCol(list)  # type: ignore[type-arg]
    created_at: datetime = Field(default_factory=utcnow)


class Problem(SQLModel, table=True):
    __tablename__ = "problems"
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=64)
    title: str = Field(max_length=120)
    statement_md: str = Field(sa_column=Column(Text))
    input_md: str = Field(default="", sa_column=Column(Text))
    output_md: str = Field(default="", sa_column=Column(Text))
    constraints_md: str = Field(default="", sa_column=Column(Text))
    biome: str = Field(index=True, max_length=24)
    rating: int
    tier: int = Field(index=True)
    base_damage: int
    base_recoil: int
    time_limit_ms: int = 2000
    memory_mb: int = 256
    checker: str = Field(default="exact", max_length=24)
    checker_script: str | None = Field(default=None, sa_column=Column(Text))
    tags: list = JsonCol(list)  # type: ignore[type-arg]
    hints: list = JsonCol(list)  # type: ignore[type-arg]
    stubs: dict = JsonCol(dict)  # type: ignore[type-arg]
    reference_solution: str = Field(default="", sa_column=Column(Text))
    status: str = Field(default="published", max_length=16)


class TestCaseRow(SQLModel, table=True):
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("problem_id", "idx"),)
    id: int | None = Field(default=None, primary_key=True)
    problem_id: int = Field(foreign_key="problems.id", index=True)
    idx: int
    input_text: str = Field(sa_column=Column(Text))
    expected_text: str = Field(sa_column=Column(Text))
    is_sample: bool = False


SIDE_FIELDS = (
    "profile_id", "name", "rating", "tier", "max_hp", "hp", "damage_dealt", "hits_landed", "skins",
    "is_bot", "blocks_left", "hints_left", "shield_until_ms", "rerolls_left", "last_reroll_ms", "hand",
    "hints_revealed", "stats", "connected",
)


class Match(SQLModel, table=True):
    """One shared row per match with player1_* and player2_* columns [Spec]."""

    __tablename__ = "matches"
    id: str = Field(primary_key=True, max_length=36)
    mode: str = Field(max_length=16, index=True)  # ranked | bot | practice | friendly | team (hook)
    map: str = Field(max_length=16)
    status: str = Field(default="starting", max_length=16, index=True)  # starting | live | finished | aborted
    seed: int
    stage_theme: str = Field(default="arena.bit", max_length=48)
    stage_owner_side: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    start_time: datetime | None = None
    end_time: datetime | None = None
    elapsed_ms: int = 0
    end_reason: str | None = Field(default=None, max_length=16)
    outcome: str | None = Field(default=None, max_length=16)
    winner_side: int | None = None
    labels: dict = JsonCol(dict)  # type: ignore[type-arg]
    result: dict = JsonCol(dict)  # type: ignore[type-arg]
    decks: dict = JsonCol(dict)  # type: ignore[type-arg]
    last_seq: int = 0

    player1_profile_id: int = Field(index=True)
    player1_name: str = ""
    player1_rating: int = 0
    player1_tier: int = 1
    player1_max_hp: int = 0
    player1_hp: int = 0
    player1_damage_dealt: int = 0
    player1_hits_landed: int = 0
    player1_skins: dict = JsonCol(dict)  # type: ignore[type-arg]
    player1_is_bot: bool = False
    player1_blocks_left: int = 0
    player1_hints_left: int = 0
    player1_shield_until_ms: int | None = None
    player1_rerolls_left: int = 0
    player1_last_reroll_ms: int | None = None
    player1_hand: dict = JsonCol(dict)  # type: ignore[type-arg]
    player1_hints_revealed: dict = JsonCol(dict)  # type: ignore[type-arg]
    player1_stats: dict = JsonCol(dict)  # type: ignore[type-arg]
    player1_connected: bool = False

    player2_profile_id: int = Field(index=True)
    player2_name: str = ""
    player2_rating: int = 0
    player2_tier: int = 1
    player2_max_hp: int = 0
    player2_hp: int = 0
    player2_damage_dealt: int = 0
    player2_hits_landed: int = 0
    player2_skins: dict = JsonCol(dict)  # type: ignore[type-arg]
    player2_is_bot: bool = False
    player2_blocks_left: int = 0
    player2_hints_left: int = 0
    player2_shield_until_ms: int | None = None
    player2_rerolls_left: int = 0
    player2_last_reroll_ms: int | None = None
    player2_hand: dict = JsonCol(dict)  # type: ignore[type-arg]
    player2_hints_revealed: dict = JsonCol(dict)  # type: ignore[type-arg]
    player2_stats: dict = JsonCol(dict)  # type: ignore[type-arg]
    player2_connected: bool = False


class Side:
    """Wraps the paired player1_*/player2_* columns so code branches on the side once."""

    __slots__ = ("m", "n")

    def __init__(self, m: Match, n: int) -> None:
        object.__setattr__(self, "m", m)
        object.__setattr__(self, "n", n)

    @property
    def other(self) -> "Side":
        return Side(self.m, 3 - self.n)

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        if name in SIDE_FIELDS:
            return getattr(self.m, f"player{self.n}_{name}")
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[no-untyped-def]
        if name not in SIDE_FIELDS:
            raise AttributeError(name)
        setattr(self.m, f"player{self.n}_{name}", value)


def sides(m: Match) -> tuple[Side, Side]:
    return Side(m, 1), Side(m, 2)


class Submission(SQLModel, table=True):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("profile_id", "cmd_id"),)
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(foreign_key="matches.id", index=True, max_length=36)
    profile_id: int = Field(index=True)
    problem_id: int
    slot: int
    language: str = Field(max_length=16)
    code: str = Field(sa_column=Column(Text))
    cmd_id: str = Field(max_length=64)
    status: str = Field(default="judging", max_length=16)  # judging | done | void
    verdict: str | None = Field(default=None, max_length=8)
    failed_test: int | None = None
    tests_passed: int = 0
    tests_total: int = 0
    time_ms: int = 0
    memory_kb: int = 0
    damage: int = 0
    recoil: int = 0
    blocked: bool = False
    crit: bool = False
    is_bot: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class MatchEvent(SQLModel, table=True):
    """Append-only event log; it can rebuild any match."""

    __tablename__ = "match_events"
    __table_args__ = (UniqueConstraint("match_id", "seq"),)
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(foreign_key="matches.id", index=True, max_length=36)
    seq: int
    t_ms: int
    type: str = Field(max_length=40)
    payload: dict = JsonCol(dict)  # type: ignore[type-arg]
    visibility: str = Field(default="both", max_length=10)  # both | p1 | p2 | spectator


class Draft(SQLModel, table=True):
    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("match_id", "profile_id", "slot", "language"),)
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(index=True, max_length=36)
    profile_id: int = Field(index=True)
    slot: int
    language: str = Field(max_length=16)
    code: str = Field(sa_column=Column(Text))
    problem_slug: str = Field(default="", max_length=64)
    updated_at: datetime = Field(default_factory=utcnow)


class Inventory(SQLModel, table=True):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("profile_id", "skin_id"),)
    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    skin_id: str = Field(max_length=48)
    acquired_at: datetime = Field(default_factory=utcnow)
    source: str = Field(default="default", max_length=16)  # default | tier | ap | achievement | admin


class Purchase(SQLModel, table=True):
    __tablename__ = "purchases"
    __table_args__ = (UniqueConstraint("profile_id", "idem_key"),)
    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)
    skin_id: str = Field(max_length=48)
    idem_key: str = Field(max_length=64)
    price: int
    created_at: datetime = Field(default_factory=utcnow)


class RatingHistory(SQLModel, table=True):
    __tablename__ = "rating_history"
    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    match_id: str = Field(index=True, max_length=36)
    before: int
    after: int
    delta: int
    steps: list = JsonCol(list)  # type: ignore[type-arg]
    multiplier: int = 100
    voided: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class QuestProgress(SQLModel, table=True):
    __tablename__ = "quest_progress"
    __table_args__ = (UniqueConstraint("profile_id", "day", "key"),)
    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)
    day: str = Field(max_length=10)
    key: str = Field(max_length=32)
    progress: int = 0
    target: int = 1
    earned_at: datetime | None = None
    claimed_at: datetime | None = None


class Achievement(SQLModel, table=True):
    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("profile_id", "key"),)
    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)
    key: str = Field(max_length=32)
    progress: int = 0
    earned_at: datetime | None = None
    claimed_at: datetime | None = None


class Flag(SQLModel, table=True):
    __tablename__ = "flags"
    id: int | None = Field(default=None, primary_key=True)
    match_id: str | None = Field(default=None, index=True, max_length=36)
    profile_id: int | None = Field(default=None, index=True)
    kind: str = Field(max_length=32)
    severity: int = 1
    details: dict = JsonCol(dict)  # type: ignore[type-arg]
    status: str = Field(default="open", max_length=16)
    created_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    actor_id: int | None = None
    action: str = Field(max_length=48)
    target: str = Field(default="", max_length=64)
    details: dict = JsonCol(dict)  # type: ignore[type-arg]
    created_at: datetime = Field(default_factory=utcnow)


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    id: int | None = Field(default=None, primary_key=True)
    reporter_id: int = Field(index=True)
    match_id: str | None = Field(default=None, max_length=36)
    target_profile_id: int | None = None
    reason: str = Field(max_length=500)
    created_at: datetime = Field(default_factory=utcnow)


Index("ix_rating_history_profile_created", RatingHistory.profile_id, RatingHistory.created_at)  # type: ignore[arg-type]

__all__ = [
    "Achievement", "AuditLog", "Draft", "Flag", "Inventory", "Match", "MatchEvent", "Problem", "Profile",
    "Purchase", "QuestProgress", "RatingHistory", "RefreshToken", "Report", "Side", "Submission",
    "TestCaseRow", "User", "sides", "utcnow",
]
