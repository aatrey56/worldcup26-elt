-- Grain: one row per match from the football-data.org v4 feed (raw.fixtures).
-- Staging extracts JSON fields, renames, and casts. The one added step is
-- country-name standardization: football-data.org spells a few nations
-- differently from the seed (Turkey vs Turkiye, United States vs USA, etc.), so
-- we map API names to the seed's canonical names via the team_name_crosswalk
-- seed. Without this, the (home_team, away_team) join to the schedule would
-- silently drop those nations' matches from dim_match and from results.
-- COUPLING NOTE: every JSON path assumes the football-data.org v4 match shape.
-- Re-verify against the live API if the provider/version changes.
-- Materialized as a table: it is re-parsed/recomputed by several downstream
-- models (int_match_map, int_results_scored, dim_match, stg_teams), so paying
-- the JSON parse once is cheaper than re-parsing per reference.

{{ config(materialized='table') }}

with src as (

    select * from {{ source('raw', 'fixtures') }}

),

crosswalk as (

    select
        api_name,
        seed_name
    from {{ ref('team_name_crosswalk') }}

),

extracted as (

    select
        fixture_id,
        cast(payload ->> '$.utcDate' as timestamp) as kickoff_utc,
        cast(payload ->> '$.lastUpdated' as timestamp) as last_updated,
        loaded_at,
        payload ->> '$.status' as status,
        payload ->> '$.homeTeam.name' as home_team_raw,
        payload ->> '$.awayTeam.name' as away_team_raw,
        payload ->> '$.homeTeam.tla' as home_team_tla,
        payload ->> '$.awayTeam.tla' as away_team_tla,
        cast((payload -> '$.score.fullTime.home') as int) as home_score,
        cast((payload -> '$.score.fullTime.away') as int) as away_score,
        payload ->> '$.stage' as stage,
        payload ->> '$.group' as group_label,
        cast((payload -> '$.matchday') as int) as matchday,
        cast((payload -> '$.homeTeam.id') as bigint) as home_team_id,
        cast((payload -> '$.awayTeam.id') as bigint) as away_team_id
    from src

)

select
    e.fixture_id,
    e.kickoff_utc,
    e.status,
    e.home_team_tla,
    e.away_team_tla,
    e.home_score,
    e.away_score,
    e.stage,
    e.group_label,
    e.matchday,
    e.home_team_id,
    e.away_team_id,
    e.last_updated,
    e.loaded_at,
    coalesce(hx.seed_name, e.home_team_raw) as home_team,
    coalesce(ax.seed_name, e.away_team_raw) as away_team
from extracted as e
left join crosswalk as hx on e.home_team_raw = hx.api_name
left join crosswalk as ax on e.away_team_raw = ax.api_name
