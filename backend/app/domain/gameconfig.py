"""Typed schema for shared/game-config.json.

This module only defines data shapes; loading the file from disk lives in
app.core.config so the domain package stays free of I/O.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierRow(_Strict):
    tier: int = Field(ge=1, le=5)
    title: str
    min_rating: int = Field(ge=0)
    max_hp: int = Field(gt=0)
    base_damage: int = Field(ge=0)
    base_recoil: int = Field(ge=0)
    seed_rating: int = Field(ge=0)


class MultiplierCfg(_Strict):
    step_pct: int
    min_pct: int
    max_pct: int


class DamageClassCfg(_Strict):
    light_below_pct: int
    heavy_below_pct: int
    massive_below_pct: int


class HandCfg(_Strict):
    size: int
    window_offset: int
    window_lo_min: int
    window_lo_max: int
    reroll_max: int
    reroll_gap_s: int
    redeal_ms: int
    prestige_min_tier: int
    min_deck_per_tier: int
    levels: list[str]  # names for a card's place in the hand window: easy, normal, medium, tough


class MapCfg(_Strict):
    id: str
    biomes: list[str]
    default_arena: str
    min_tier: int


class MatchCfg(_Strict):
    max_minutes: int
    countdown_s: int
    connect_grace_s: int
    disconnect_grace_s: int
    submit_cooldown_s: int
    timer_broadcast_s: int
    early_leave_s: int
    registry_linger_s: int
    max_code_bytes: int
    snapshot_gap: int
    no_show_strikes: int
    no_show_ban_min: int
    emote_cooldown_s: int


class BlockCfg(_Strict):
    charges: int
    window_s: int


class HintCfg(_Strict):
    charges: int
    levels: int


class PowerupsCfg(_Strict):
    block: BlockCfg
    hint: HintCfg


class SpeedBracket(_Strict):
    name: str
    max_s: int
    bonus: int


class RatingCfg(_Strict):
    starting: int
    floor: int
    win: int
    rank_gap: int
    flawless_points: int
    flawless_bonus: int
    narrow_win_share_pct: int
    narrow_win_penalty: int
    speed_brackets: list[SpeedBracket]
    slow_bracket_name: str
    bot_multiplier_pct: int
    bot_daily_gain_cap: int
    friendly_multiplier_pct: int
    rematch_multiplier_pct: list[int]
    rematch_window_min: int


class MatchmakingCfg(_Strict):
    window_start: int
    window_step: int
    window_step_s: int
    window_max: int
    ready_check_s: int
    bot_fallback_s: int
    tick_ms: int
    recent_opponent_min: int
    recent_override_wait_s: int
    decline_cooldown_s: int
    same_ip_block: bool
    lobby_leave_grace_s: int


class LanguageCfg(_Strict):
    id: str
    name: str
    monaco: str
    run: str  # argv; {src} is the source file
    file: str
    time_multiplier: int  # problem time limits are set for C++; slower languages get a multiple
    compile: str | None = None  # argv; {src} the source, {include} the harness's include dir
    comment: str = "#"  # line-comment marker (the test judge's "VERDICT" markers, templates)
    judge0_id: int | None = None


class JudgeCfg(_Strict):
    stop_on_first_fail: bool
    compile_time_s: int = 20
    compile_memory_mb: int = 1536
    concurrency: int
    time_limit_ms: int
    memory_mb: int
    output_limit_kb: int
    source_limit_kb: int
    input_limit_kb: int
    custom_input_limit_kb: int
    wall_factor: int
    wall_extra_ms: int
    max_processes: int
    dev_fsize_mb: int
    job_timeout_s: int
    queue_timeout_s: int
    max_queued: int
    run_time_cap_ms: int
    run_wait_s: int
    stderr_tail_kb: int
    system_error_flag_after: int


class BucketCfg(_Strict):
    capacity: int
    per_s: float


class RateLimitsCfg(_Strict):
    login: BucketCfg
    signup: BucketCfg
    run: BucketCfg
    queue_join: BucketCfg
    rest: BucketCfg
    ws_msgs: BucketCfg


class PersonalityCfg(_Strict):
    slot_weights: list[int]
    prefer_on_level: bool
    time_scale: float
    skill_offset: float
    block_below_pct: int
    weapon: str = "weapon.fireball"  # cosmetic only


class BotsCfg(_Strict):
    think_median_s: list[float]
    think_sigma: float
    miss_wait_s: list[float]
    judge_delay_s: list[float]
    rating_spread: int
    default_personality: str
    personalities: dict[str, PersonalityCfg]
    names: list[str]


class EconomyCfg(_Strict):
    match: int
    win: int
    draw: int
    per_hit: int
    per_match_hit_cap: int
    flawless: int
    blitz: int
    first_win_of_day: int
    streak_per_level: int
    streak_cap: int
    casual_modes_pct: int
    casual_modes_daily_cap: int
    tutorial_reward: int


class QuestCfg(_Strict):
    id: str
    kind: str
    target: int
    ap: int
    map: str | None = None


class AchievementCfg(_Strict):
    id: str
    reward: str
    target: int | None = None
    hp_pct: int | None = None
    min_s: int | None = None


class QualityPreset(_Strict):
    max_particles: int
    dpr_cap: int


class GameConfig(_Strict):
    game_name: str
    config_version: int
    tiers: list[TierRow]
    tier_colors: list[str]
    multiplier: MultiplierCfg
    scenarios: dict[str, str]
    damage_classes: DamageClassCfg
    crit_max_tier_diff: int
    hand: HandCfg
    maps: list[MapCfg]
    match: MatchCfg
    powerups: PowerupsCfg
    rating: RatingCfg
    matchmaking: MatchmakingCfg
    languages: list[LanguageCfg]
    judge: JudgeCfg
    rate_limits: RateLimitsCfg
    bots: BotsCfg
    economy: EconomyCfg
    quests: list[QuestCfg]
    quests_per_day: int
    achievements: list[AchievementCfg]
    emotes: list[str]
    features: dict[str, bool]
    quality: dict[str, QualityPreset]
    bot_time_scale: float

    @model_validator(mode="after")
    def _check(self) -> GameConfig:
        tiers = [t.tier for t in self.tiers]
        if tiers != list(range(1, len(tiers) + 1)):
            raise ValueError("tiers must be listed 1..N in order")
        mins = [t.min_rating for t in self.tiers]
        if mins[0] != 0 or mins != sorted(mins):
            raise ValueError("tier min_rating must start at 0 and increase")
        if len(self.tier_colors) != len(self.tiers):
            raise ValueError("one tier colour per tier")
        n = len(self.tiers)
        for d in range(-(n - 1), n):
            if str(d) not in self.scenarios:
                raise ValueError(f"missing scenario name for tier_diff {d}")
        if self.hand.size != 4:
            raise ValueError("the game is designed around a hand of four cards")
        if self.bots.default_personality not in self.bots.personalities:
            raise ValueError("default bot personality is not defined")
        if len(self.bots.think_median_s) != n:
            raise ValueError("one bot think median per tier")
        for p in self.bots.personalities.values():
            if len(p.slot_weights) != self.hand.size or sum(p.slot_weights) <= 0:
                raise ValueError("bot slot_weights must have one positive-sum weight per hand slot")
        if len(self.hand.levels) != self.hand.size:
            raise ValueError("hand.levels needs one name per hand slot")
        ids = [m.id for m in self.maps]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate map id")
        brackets = [b.max_s for b in self.rating.speed_brackets]
        if brackets != sorted(brackets):
            raise ValueError("speed brackets must be in increasing order")
        return self

    # Convenience lookups -------------------------------------------------
    def tier_row(self, tier: int) -> TierRow:
        return self.tiers[tier - 1]

    def map_cfg(self, map_id: str) -> MapCfg:
        for m in self.maps:
            if m.id == map_id:
                return m
        raise KeyError(map_id)

    def language(self, lang_id: str) -> LanguageCfg:
        for lang in self.languages:
            if lang.id == lang_id:
                return lang
        raise KeyError(lang_id)

    def feature(self, name: str) -> bool:
        return bool(self.features.get(name, False))
