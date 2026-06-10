-- Grain: one row per FIFA timeline event (raw.fifa_events).
-- A clean 1:1 projection of the enriched event payload landed by the loader.
-- MatchMinute arrives as a string like "5'"; we strip the trailing quote and
-- cast to int (null-safe via try_cast). event_desc/x_norm/y_norm and the shot
-- geometry were computed in the loader (see include/extract/load_fifa.py) so the
-- per-match coordinate-scale decision and xG geometry live in Python, not SQL.
-- pos_x_raw/pos_y_raw are the original (un-normalized, signed/centred) FIFA
-- coordinates, kept for traceability. Empty pre-tournament (no played matches).
-- COUPLING NOTE: assumes the loader-enriched event shape.

with src as (

    select * from {{ source('raw', 'fifa_events') }}

)

select
    match_id,
    event_idx,
    cast(payload ->> '$.Type' as int) as event_type,
    payload ->> '$.event_desc' as event_desc,
    cast(payload ->> '$.IdPlayer' as bigint) as player_id,
    cast(payload ->> '$.IdTeam' as bigint) as team_id,
    try_cast(replace(payload ->> '$.MatchMinute', '''', '') as int) as minute,
    cast(payload ->> '$.PositionX' as double) as pos_x_raw,
    cast(payload ->> '$.PositionY' as double) as pos_y_raw,
    cast(payload ->> '$.GoalGatePositionY' as double) as goal_y,
    cast(payload ->> '$.GoalGatePositionZ' as double) as goal_z,
    loaded_at
from src
