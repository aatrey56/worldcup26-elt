-- Grain: one row per shot event (raw.fifa_events filtered to is_shot).
-- A shot is an "Attempt at Goal", "Goal!", "Penalty Goal", or "Penalty missed".
-- "Penalty Awarded" is the award of a penalty, NOT a shot, so it is excluded
-- (the loader's is_shot flag already encodes this; we filter on it).
--
-- NORMALIZED COORDINATES + GEOMETRY (computed in the loader, read 1:1 here):
--   x, y       coordinates in a 0-1 frame where the attacked goal is at
--              x=1, y=0.5. The raw FIFA frame is centred (X in [-1,1] with the
--              goal at |X|=1, Y in [-0.5,0.5] centred at 0) and varies in scale
--              between seasons (0-1 vs metric); the loader detects the scale per
--              match and maps it via normalize_xy (x = |X|, y = Y + 0.5). Doing
--              this in the loader keeps the per-match scale decision out of SQL.
--   shot_distance   Euclidean distance from (x, y) to the goal centre (1, 0.5)
--                   in normalized units.
--   shot_angle      angle (radians) subtended by the 7.32m goal mouth (0.1076 of
--                   the 68m-wide pitch, posts at y = 0.5 +/- 0.0538) at the shot
--                   location. Standard xG geometry: larger = better sight of goal.
-- is_penalty rows sit at x ~ 0.79 (the penalty spot), y = 0.5, distance ~ 0.21.
-- Empty pre-tournament. COUPLING NOTE: assumes the loader-enriched event shape.

with src as (

    select * from {{ source('raw', 'fifa_events') }}
    where cast(payload ->> '$.is_shot' as boolean)

)

select
    match_id,
    cast(payload ->> '$.IdPlayer' as bigint) as player_id,
    cast(payload ->> '$.IdTeam' as bigint) as team_id,
    try_cast(replace(payload ->> '$.MatchMinute', '''', '') as int) as minute,
    cast(payload ->> '$.x_norm' as double) as x,
    cast(payload ->> '$.y_norm' as double) as y,
    cast(payload ->> '$.GoalGatePositionY' as double) as goal_y,
    cast(payload ->> '$.GoalGatePositionZ' as double) as goal_z,
    cast(payload ->> '$.is_goal' as boolean) as is_goal,
    cast(payload ->> '$.is_penalty' as boolean) as is_penalty,
    payload ->> '$.shot_outcome' as shot_outcome,
    cast(payload ->> '$.shot_distance' as double) as shot_distance,
    cast(payload ->> '$.shot_angle' as double) as shot_angle,
    loaded_at
from src
