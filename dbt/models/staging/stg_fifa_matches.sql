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
    cast(payload ->> '$.IdStage' as bigint) as stage_id,
    cast(payload ->> '$.MatchStatus' as int) as status,
    -- StageName localized [0].Description, e.g. 'First Stage', 'Round of 32'.
    payload ->> '$.StageName[0].Description' as stage_name,
    -- GroupName localized [0].Description, e.g. 'Group A'; null for knockout.
    payload ->> '$.GroupName[0].Description' as group_name,
    -- LastPeriodUpdate is FIFA's last in-play update timestamp; it is null until
    -- the match goes live, so downstream coalesces it to loaded_at.
    cast(payload ->> '$.LastPeriodUpdate' as timestamp) as last_period_update,
    cast(payload ->> '$.Home.IdTeam' as bigint) as home_team_id,
    payload ->> '$.Home.TeamName[0].Description' as home_team_name,
    cast(payload ->> '$.Away.IdTeam' as bigint) as away_team_id,
    payload ->> '$.Away.TeamName[0].Description' as away_team_name,
    cast(payload ->> '$.HomeTeamScore' as int) as home_score,
    cast(payload ->> '$.AwayTeamScore' as int) as away_score,
    cast(payload ->> '$.BallPossession.OverallHome' as double) as home_possession,
    cast(payload ->> '$.BallPossession.OverallAway' as double) as away_possession,
    loaded_at
from src
