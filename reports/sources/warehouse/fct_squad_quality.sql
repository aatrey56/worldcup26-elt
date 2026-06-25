-- Squad-quality context stat: one row per team with its top-5-league player
-- count. Empty if the Wikipedia squads load degraded, and Evidence
-- (universal-sql 3.0.1) writes a zero-byte parquet for an empty source, which
-- breaks the build (issue 2466). A single typed all-null sentinel is added ONLY
-- when the table is empty so the parquet is always valid. The squads page guards
-- on length > 0 and the null-team_key sentinel is filtered out, so it never
-- renders. group_letter is joined from dim_team for the page's group context.
select
  q.team_key,
  q.team_name,
  t.fifa_code,
  t.group_letter,
  q.squad_size,
  q.top5_count,
  q.top5_pct
from main.fct_squad_quality q
inner join main.dim_team t
  on q.team_key = t.team_key

union all

select
  cast(null as varchar)  as team_key,
  cast(null as varchar)  as team_name,
  cast(null as varchar)  as fifa_code,
  cast(null as varchar)  as group_letter,
  cast(null as bigint)   as squad_size,
  cast(null as bigint)   as top5_count,
  cast(null as double)   as top5_pct
where not exists (select 1 from main.fct_squad_quality)
