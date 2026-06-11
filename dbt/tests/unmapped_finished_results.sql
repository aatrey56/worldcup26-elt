-- DATA-QUALITY GATE: alert on silent result loss at the reconciliation layer.
--
-- int_results_scored builds one row per match_no by mapping each source's own
-- ids to the seed match_no (FIFA via int_fifa_match_map, football-data via
-- int_match_map) and then filters `where match_no is not null`. That filter is
-- correct (a row with no match_no cannot land in the star schema), but it means
-- a genuinely scored match whose id FAILS to reconcile is dropped SILENTLY,
-- before it ever reaches int_results_scored. That is exactly the failure this
-- feature exists to prevent (a live or finished score vanishing from the site).
--
-- So this test inspects the SOURCE rows, not int_results_scored: it returns a
-- row (fails the build) for any match that is genuinely scored at the source but
-- has no mapping to a seed match_no:
--   FIFA: status in (0, 3, 12) with both scores non-null but match_id absent
--         from int_fifa_match_map (a crosswalk/group_letter/positional gap).
--   football-data: status = 'FINISHED' with both scores non-null but fixture_id
--         absent from int_match_map.
-- A mapping gap therefore fails LOUDLY instead of quietly dropping a result.
--
-- (The previous version keyed on int_results_scored.match_no vs dim_match, which
-- was vacuous: int_results_scored only emits non-null match_no, and dim_match
-- holds all 104 seed match_nos, so it could never fire.)

with fifa_scored_src as (

    select
        match_id as source_id,
        'fifa' as source
    from {{ ref('stg_fifa_matches') }}
    where
        status in (0, 3, 12)
        and home_score is not null
        and away_score is not null

),

fifa_unmapped as (

    select
        s.source_id,
        s.source
    from fifa_scored_src as s
    left join {{ ref('int_fifa_match_map') }} as m
        on s.source_id = m.fifa_match_id
    where m.fifa_match_id is null

),

fd_scored_src as (

    select
        fixture_id as source_id,
        'football-data' as source
    from {{ ref('stg_matches') }}
    where
        status = 'FINISHED'
        and home_score is not null
        and away_score is not null

),

fd_unmapped as (

    select
        s.source_id,
        s.source
    from fd_scored_src as s
    left join {{ ref('int_match_map') }} as m
        on s.source_id = m.fixture_id
    where m.fixture_id is null

)

select
    cast(source_id as varchar) as source_id,
    source
from fifa_unmapped

union all

select
    cast(source_id as varchar) as source_id,
    source
from fd_unmapped
