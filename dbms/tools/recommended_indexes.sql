-- Indexes the app does not create today that the timings in 05_query_timings.md
-- show would pay off. Measured by creating them, re-running every query, and
-- dropping them again (plans/with_recommended_indexes/).
CREATE INDEX ix_matches_created_at ON matches (created_at);                                  -- Q61 admin list
CREATE INDEX ix_matches_finished_end_time ON matches (end_time) WHERE status = 'finished';   -- Q25 weekly board
CREATE INDEX ix_matches_map_winners ON matches (map)
    INCLUDE (winner_side, player1_profile_id, player2_profile_id)
    WHERE status = 'finished' AND winner_side IS NOT NULL;                                   -- Q26 map board (index-only)
CREATE INDEX ix_profiles_ladder ON profiles (rating DESC, lower(display_name))
    WHERE NOT is_bot AND user_id IS NOT NULL;                                                -- Q24 all-time board, Q23 rank
CREATE INDEX ix_profiles_display_name_lower ON profiles (lower(display_name));                -- Q14 profile by name
CREATE INDEX ix_profiles_bot_personality ON profiles (personality) WHERE is_bot;              -- Q30, Q76 bots
