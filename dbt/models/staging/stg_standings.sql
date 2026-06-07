-- Grain: one row per team-in-group from the API-Football v3 standings feed
-- (raw.standings). Staging is 1:1 with source: extract, rename, cast. No logic.
-- COUPLING NOTE: every path below assumes the API-Football v3 standings entry
-- shape. Re-verify against the live API if the provider/version changes.

with src as (

    select * from {{ source('raw', 'standings') }}

)

select
    team_id,
    group_label,
    (payload -> '$.rank')::int                  as rank,
    payload ->> '$.team.name'                   as team_name,
    (payload -> '$.points')::int                as points,
    (payload -> '$.goalsDiff')::int             as goals_diff,
    payload ->> '$.group'                        as group_name,
    (payload -> '$.all.played')::int            as played,
    (payload -> '$.all.win')::int               as won,
    (payload -> '$.all.draw')::int              as drawn,
    (payload -> '$.all.lose')::int              as lost,
    (payload -> '$.all.goals.for')::int         as goals_for,
    (payload -> '$.all.goals.against')::int     as goals_against
from src
