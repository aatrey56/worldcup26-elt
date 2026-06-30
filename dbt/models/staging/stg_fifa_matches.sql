-- Grain: one row per FIFA calendar match (raw.fifa_matches).
-- Staging extracts JSON fields, renames, and casts from the FIFA v3 calendar
-- match shape. Team names and group come from FIFA's localized list shape
-- ([{Locale, Description}]), so we read [0].Description. Scores and possession
-- are null pre-tournament; ball possession lives under BallPossession.Overall*.
-- COUPLING NOTE: every JSON path assumes the api.fifa.com v3 calendar shape
-- (undocumented). Re-verify if FIFA changes the feed.

with src as (

    select * from {{ source('raw', 'fifa_matches') }}

)

select
    match_id,
    cast(payload ->> '$.Date' as timestamp) as match_date,
    cast(payload ->> '$.IdSeason' as bigint) as season_id,
    cast(payload ->> '$.IdStage' as bigint) as stage_id,
    cast(payload ->> '$.MatchStatus' as int) as status,
    -- StageName localized [0].Description, e.g. 'First Stage', 'Round of 32'.
    payload ->> '$.StageName[0].Description' as stage_name,
    -- GroupName localized [0].Description, e.g. 'Group A'; null for knockout.
    payload ->> '$.GroupName[0].Description' as group_name,
    cast(payload ->> '$.Home.IdTeam' as bigint) as home_team_id,
    payload ->> '$.Home.TeamName[0].Description' as home_team_name,
    cast(payload ->> '$.Away.IdTeam' as bigint) as away_team_id,
    payload ->> '$.Away.TeamName[0].Description' as away_team_name,
    cast(payload ->> '$.HomeTeamScore' as int) as home_score,
    cast(payload ->> '$.AwayTeamScore' as int) as away_score,
    -- penalty-shootout scores; null unless a knockout went to a shootout. Their
    -- presence is the shootout indicator (and they drive the "(4-3 pens)" display).
    cast(payload ->> '$.HomeTeamPenaltyScore' as int) as home_penalty_score,
    cast(payload ->> '$.AwayTeamPenaltyScore' as int) as away_penalty_score,
    -- FIFA's resolved winner team id: set for any DECIDED knockout (normal time,
    -- extra time, OR penalties), so it cleanly carries the shootout winner that a
    -- level full-time score cannot. Null for draws and unplayed matches.
    cast(payload ->> '$.Winner' as bigint) as winner_team_id,
    cast(payload ->> '$.BallPossession.OverallHome' as double) as home_possession,
    cast(payload ->> '$.BallPossession.OverallAway' as double) as away_possession,
    loaded_at
from src
