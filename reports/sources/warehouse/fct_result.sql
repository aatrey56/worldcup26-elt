-- One row per finished match. Pre-tournament this table is empty, and Evidence
-- (universal-sql 3.0.1) writes a zero-byte parquet for an empty source, which
-- breaks the build (issue 2466). The union adds a single typed all-null
-- sentinel row ONLY when the table is empty, so the parquet is always valid.
-- Every page consumes fct_result via INNER JOINs on match_key / team_key, all
-- null in the sentinel, so the sentinel never renders.
select
  match_key,
  home_team_key,
  away_team_key,
  home_score,
  away_score,
  result,
  is_live,
  source,
  winner_team_key,
  played_at,
  loaded_at
from main.fct_result

union all

select
  cast(null as varchar)                     as match_key,
  cast(null as varchar)                     as home_team_key,
  cast(null as varchar)                     as away_team_key,
  cast(null as integer)                     as home_score,
  cast(null as integer)                     as away_score,
  cast(null as varchar)                     as result,
  cast(null as boolean)                     as is_live,
  cast(null as varchar)                     as source,
  cast(null as varchar)                     as winner_team_key,
  cast(null as timestamp)                   as played_at,
  cast(null as timestamptz)                 as loaded_at
where not exists (select 1 from main.fct_result)
