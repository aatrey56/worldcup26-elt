-- One row per player who has taken a shot: the custom-xG leaderboard. Empty
-- pre-tournament, and Evidence (universal-sql 3.0.1) writes a zero-byte parquet
-- for an empty source, which breaks the build (issue 2466). A single typed
-- all-null sentinel is added ONLY when the table is empty so the parquet is
-- always valid. The xG page guards on length > 0 and filters the null-player_id
-- sentinel, so it never renders.
select
  player_id,
  player_name,
  position,
  team_id,
  shots,
  goals,
  total_xg,
  xg_per_shot,
  finishing
from main.agg_player_xg

union all

select
  cast(null as bigint)                      as player_id,
  cast(null as varchar)                     as player_name,
  cast(null as varchar)                     as position,
  cast(null as bigint)                      as team_id,
  cast(null as bigint)                      as shots,
  cast(null as hugeint)                     as goals,
  cast(null as double)                      as total_xg,
  cast(null as double)                      as xg_per_shot,
  cast(null as double)                      as finishing
where not exists (select 1 from main.agg_player_xg)
