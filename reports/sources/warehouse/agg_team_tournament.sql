-- One row per team. Empty until the first finished match; a typed all-null
-- sentinel is added ONLY when empty to keep the Evidence parquet valid (issue
-- 2466). No page queries this source, so the sentinel is never displayed.
select
  team_key,
  matches_played,
  wins,
  draws,
  losses,
  gf,
  ga,
  gd,
  points,
  stage_reached
from main.agg_team_tournament

union all

select
  cast(null as varchar)                     as team_key,
  cast(null as bigint)                      as matches_played,
  cast(null as hugeint)                     as wins,
  cast(null as hugeint)                     as draws,
  cast(null as hugeint)                     as losses,
  cast(null as hugeint)                     as gf,
  cast(null as hugeint)                     as ga,
  cast(null as hugeint)                     as gd,
  cast(null as hugeint)                     as points,
  cast(null as varchar)                     as stage_reached
where not exists (select 1 from main.agg_team_tournament)
