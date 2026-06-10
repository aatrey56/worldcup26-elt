-- Grain: one row per match from the football-data.org v4 feed (raw.fixtures).
-- Staging extracts JSON fields, renames, and casts. The one added step is
-- country-name standardization: football-data.org spells a few nations
-- differently from the seed (Turkey vs Turkiye, United States vs USA, etc.), so
-- we map API names to the seed's canonical names via the team_name_crosswalk
-- seed. Without this, the (home_team, away_team) join to the schedule would
-- silently drop those nations' matches from dim_match and from results.
-- COUPLING NOTE: every JSON path assumes the football-data.org v4 match shape.
-- Re-verify against the live API if the provider/version changes.

with src as (

    select * from {{ source('raw', 'fixtures') }}

),

crosswalk as (

    select api_name, seed_name from {{ ref('team_name_crosswalk') }}

),

extracted as (

    select
        fixture_id,
        cast(payload ->> '$.utcDate' as timestamp)            as kickoff_utc,
        payload ->> '$.status'                                 as status,
        payload ->> '$.homeTeam.name'                          as home_team_raw,
        payload ->> '$.awayTeam.name'                          as away_team_raw,
        (payload -> '$.score.fullTime.home')::int             as home_score,
        (payload -> '$.score.fullTime.away')::int             as away_score,
        payload ->> '$.stage'                                  as stage,
        payload ->> '$.group'                                  as group_label,
        (payload -> '$.matchday')::int                        as matchday,
        (payload -> '$.homeTeam.id')::bigint                  as home_team_id,
        (payload -> '$.awayTeam.id')::bigint                  as away_team_id,
        loaded_at
    from src

)

select
    e.fixture_id,
    e.kickoff_utc,
    e.status,
    coalesce(hx.seed_name, e.home_team_raw)               as home_team,
    coalesce(ax.seed_name, e.away_team_raw)               as away_team,
    e.home_score,
    e.away_score,
    e.stage,
    e.group_label,
    e.matchday,
    e.home_team_id,
    e.away_team_id,
    e.loaded_at
from extracted e
left join crosswalk hx on e.home_team_raw = hx.api_name
left join crosswalk ax on e.away_team_raw = ax.api_name
