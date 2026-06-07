-- Grain: one row per FINISHED match (status_short = 'FT').
-- Derives result and points, then attaches match_no/group_letter from the
-- schedule by joining on the (home_team, away_team) name pair only.
-- NOTE: we deliberately do NOT join on date. The seed date is ET local while
-- the API date is UTC, so they can differ by a day across midnight.

with matches as (

    select *
    from {{ ref('stg_matches') }}
    where status_short = 'FT'

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

schedule as (

    select
        match_no,
        group_letter,
        home_team,
        away_team
    from {{ ref('stg_schedule') }}
    where not is_placeholder

)

select
    s.fixture_id,
    sch.match_no,
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
left join schedule sch
    on s.home_team = sch.home_team
   and s.away_team = sch.away_team
