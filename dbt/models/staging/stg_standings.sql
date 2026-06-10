-- Grain: one row per team from the football-data.org v4 TOTAL standings table
-- (raw.standings). Staging is 1:1 with source: extract, rename, cast. No logic.
-- Auxiliary cross-check model only: the marts recompute standings from results.
-- COUPLING NOTE: every path below assumes the football-data.org v4 standings
-- table-row shape (with group injected by the loader). Re-verify on provider
-- changes.

with src as (

    select * from {{ source('raw', 'standings') }}

),

crosswalk as (

    select api_name, seed_name from {{ ref('team_name_crosswalk') }}

)

select
    src.team_id,
    coalesce(cw.seed_name, src.payload ->> '$.team.name') as team_name,
    (src.payload -> '$.position')::int          as position,
    (src.payload -> '$.playedGames')::int       as played_games,
    (src.payload -> '$.won')::int               as won,
    (src.payload -> '$.draw')::int              as draw,
    (src.payload -> '$.lost')::int              as lost,
    (src.payload -> '$.points')::int            as points,
    (src.payload -> '$.goalsFor')::int          as goals_for,
    (src.payload -> '$.goalsAgainst')::int      as goals_against,
    (src.payload -> '$.goalDifference')::int    as goal_difference,
    src.payload ->> '$.group'                   as group_label,
    src.loaded_at
from src
left join crosswalk cw
    on (src.payload ->> '$.team.name') = cw.api_name
