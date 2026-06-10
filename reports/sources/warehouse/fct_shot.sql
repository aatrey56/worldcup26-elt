-- One row per shot, scored with the custom xG model. Empty pre-tournament, and
-- Evidence (universal-sql 3.0.1) writes a zero-byte parquet for an empty source,
-- which breaks the build (issue 2466). A single typed all-null sentinel is added
-- ONLY when the table is empty so the parquet is always valid. The shots page
-- guards on length > 0 and filters the null-x sentinel, so it never renders.
select
  match_id,
  player_id,
  team_id,
  minute,
  x,
  y,
  shot_distance,
  shot_angle,
  is_goal,
  is_penalty,
  xg
from main.fct_shot

union all

select
  cast(null as bigint)                      as match_id,
  cast(null as bigint)                      as player_id,
  cast(null as bigint)                      as team_id,
  cast(null as integer)                     as minute,
  cast(null as double)                      as x,
  cast(null as double)                      as y,
  cast(null as double)                      as shot_distance,
  cast(null as double)                      as shot_angle,
  cast(null as boolean)                     as is_goal,
  cast(null as boolean)                     as is_penalty,
  cast(null as double)                      as xg
where not exists (select 1 from main.fct_shot)
