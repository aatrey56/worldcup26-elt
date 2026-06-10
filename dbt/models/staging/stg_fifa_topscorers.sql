-- Grain: one row per player from the FIFA season top-scorers feed
-- (raw.fifa_topscorers). Staging extracts JSON fields from the PlayerStatsList
-- entry shape: player identity nests under PlayerInfo, stats are top-level.
-- Player name comes from FIFA's localized list ([{Locale, Description}]), so we
-- read [0].Description. Empty pre-tournament (no goals scored yet).
-- COUPLING NOTE: assumes the api.fifa.com v3 topscorers PlayerStatsList shape.

with src as (

    select * from {{ source('raw', 'fifa_topscorers') }}

)

select
    player_id,
    payload ->> '$.PlayerInfo.PlayerName[0].Description' as player_name,
    payload ->> '$.PlayerInfo.IdCountry' as country_code,
    cast(payload ->> '$.PlayerInfo.IdTeam' as bigint) as team_id,
    cast(payload ->> '$.Rank' as int) as rank,
    cast(payload ->> '$.GoalsScored' as int) as goals,
    cast(payload ->> '$.Assists' as int) as assists,
    cast(payload ->> '$.GoalsScoredOnPenalty' as int) as penalty_goals,
    cast(payload ->> '$.MatchesPlayed' as int) as matches_played,
    cast(payload ->> '$.TotalAttempts' as int) as total_attempts,
    cast(payload ->> '$.AttemptsOnTarget' as int) as attempts_on_target,
    loaded_at
from src
