-- Golden boot race: one row per scorer in the FIFA top-scorers feed. Empty
-- pre-tournament, and Evidence (universal-sql 3.0.1) writes a zero-byte parquet
-- for an empty source, which breaks the build (issue 2466). A single typed
-- all-null sentinel is added ONLY when the table is empty so the parquet is
-- always valid. The scorers page guards on length > 0 and the null-rank
-- sentinel is filtered out, so it never renders.
select
  rank,
  player_id,
  player_name,
  team_id,
  team_name,
  goals,
  assists
from main.agg_top_scorers

union all

select
  cast(null as integer)                     as rank,
  cast(null as bigint)                      as player_id,
  cast(null as varchar)                     as player_name,
  cast(null as bigint)                      as team_id,
  cast(null as varchar)                     as team_name,
  cast(null as integer)                     as goals,
  cast(null as integer)                     as assists
where not exists (select 1 from main.agg_top_scorers)
