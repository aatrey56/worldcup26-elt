-- One row per team per group. Empty until the first group result, so a typed
-- all-null sentinel is added ONLY when the table is empty to keep the Evidence
-- parquet valid (issue 2466). Pages join this to dim_team on team_key (null in
-- the sentinel) via INNER JOIN, so the sentinel never renders.
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
  rank,
  qualified_flag
from main.fct_group_standings

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
  cast(null as bigint)                      as rank,
  cast(null as boolean)                     as qualified_flag
where not exists (select 1 from main.fct_group_standings)
