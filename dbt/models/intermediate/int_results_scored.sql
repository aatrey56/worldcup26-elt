-- Grain: one row per genuinely SCORED match.
-- A match counts as scored only when status = 'FINISHED' AND both fullTime
-- scores are non-null (FIX 6): a FINISHED match with null scores (awarded /
-- abandoned) is excluded rather than mislabelled as a 0-0 draw.
--
-- Derives result and points, then attaches match_no / group_letter via the
-- stable fixture_id reconciliation (int_match_map), NOT the old fragile
-- (home_team, away_team) name-pair join (FIX 1/4/7). The id-based path lands
-- knockout results and survives name drift.
--
-- Materialized as a table: it is recomputed by several downstream models
-- (fct_result, int_group_table), so we compute it once.

{{ config(materialized='table') }}

with matches as (

    select *
    from {{ ref('stg_matches') }}
    where status = 'FINISHED'
      and home_score is not null
      and away_score is not null

),

scored as (

    select
        fixture_id,
        kickoff_utc,
        loaded_at,
        home_team,
        away_team,
        home_score,
        away_score,
        case
            when home_score > away_score then 'home_win'
            when home_score < away_score then 'away_win'
            else 'draw'
        end as result,
        case
            when home_score > away_score then 3
            when home_score = away_score then 1
            else 0
        end as home_points,
        case
            when away_score > home_score then 3
            when away_score = home_score then 1
            else 0
        end as away_points
    from matches

),

match_map as (

    select fixture_id, match_no
    from {{ ref('int_match_map') }}

),

schedule as (

    select match_no, group_letter
    from {{ ref('stg_schedule') }}

)

select
    s.fixture_id,
    mm.match_no,
    sch.group_letter,
    s.kickoff_utc,
    s.loaded_at                                as source_loaded_at,
    s.home_team,
    s.away_team,
    s.home_score,
    s.away_score,
    s.result,
    s.home_points,
    s.away_points
from scored s
left join match_map mm
    on s.fixture_id = mm.fixture_id
left join schedule sch
    on mm.match_no = sch.match_no
