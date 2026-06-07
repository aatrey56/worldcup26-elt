-- Grain: one row per fixture from the API-Football v3 feed (raw.fixtures).
-- Staging is 1:1 with source: extract JSON fields, rename, cast. No logic.
-- COUPLING NOTE: every path below assumes the API-Football v3 fixture shape.
-- Re-verify against the live API if the provider/version changes.

with src as (

    select * from {{ source('raw', 'fixtures') }}

)

select
    fixture_id,
    cast(payload ->> '$.fixture.date' as timestamp)        as kickoff_utc,
    payload ->> '$.fixture.status.short'                    as status_short,
    payload ->> '$.teams.home.name'                         as home_team,
    payload ->> '$.teams.away.name'                         as away_team,
    (payload -> '$.goals.home')::int                        as home_score,
    (payload -> '$.goals.away')::int                        as away_score,
    payload ->> '$.fixture.venue.name'                      as venue_name,
    payload ->> '$.fixture.venue.city'                      as venue_city,
    payload ->> '$.league.round'                            as round_label,
    (payload -> '$.teams.home.id')::bigint                  as home_team_id,
    (payload -> '$.teams.away.id')::bigint                  as away_team_id,
    loaded_at
from src
