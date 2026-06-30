-- One row per team per group: the LIVE provisional standings (in-play scores
-- folded in) with per-team live status/score. Normally 48 rows (all group teams
-- via a left join from dim_team), but a typed all-null sentinel is added when the
-- table is empty so the Evidence parquet stays valid (issue 2466). Pages inner
-- join dim_team on team_key (null in the sentinel), so the sentinel never renders.
select
  group_letter,
  team_key,
  played,
  won,
  drawn,
  lost,
  gf,
  ga,
  gd,
  points,
  is_playing,
  points_live_delta,
  live_for,
  live_against,
  live_status,
  fifa_rank,
  rank
from main.fct_group_standings_live

union all

select
  cast(null as varchar)                     as group_letter,
  cast(null as varchar)                     as team_key,
  cast(null as hugeint)                     as played,
  cast(null as hugeint)                     as won,
  cast(null as hugeint)                     as drawn,
  cast(null as hugeint)                     as lost,
  cast(null as hugeint)                     as gf,
  cast(null as hugeint)                     as ga,
  cast(null as hugeint)                     as gd,
  cast(null as hugeint)                     as points,
  cast(null as boolean)                     as is_playing,
  cast(null as hugeint)                     as points_live_delta,
  cast(null as integer)                     as live_for,
  cast(null as integer)                     as live_against,
  cast(null as varchar)                     as live_status,
  cast(null as integer)                     as fifa_rank,
  cast(null as bigint)                      as rank
where not exists (select 1 from main.fct_group_standings_live)
