-- Grain: one row per (group_letter, team) recomputed from FINISHED group
-- matches in int_results_scored. Aggregates played/won/drawn/lost/gf/ga/gd/
-- points, then ranks within each group.
--
-- LIVE EXCLUSION: only finished matches move the table, so in-play FIFA rows
-- (is_live = true) are excluded here. A live score therefore shows on the
-- dashboard (via fct_result) but does not alter the standings until full time,
-- which keeps ranks/qualification deterministic mid-match.
--
-- TIEBREAKER: this model implements only the first three criteria of the
-- official FIFA ordering: (1) points DESC, (2) goal difference DESC,
-- (3) goals scored DESC.
-- The FULL official FIFA order is:
--   1. points
--   2. goal difference
--   3. goals scored
--   4. head-to-head points (among tied teams)
--   5. head-to-head goal difference
--   6. head-to-head goals scored
--   7. fair-play points
--   8. drawing of lots
-- Criteria 4-8 require head-to-head and disciplinary data not yet ingested,
-- so they are NOT implemented here.

with group_results as (

    select *
    from {{ ref('int_results_scored') }}
    where group_letter is not null and not is_live

),

per_team as (

    -- one row per team appearance (home side). won/drawn/lost are derived
    -- from the points column already produced by int_results_scored
    -- (3 = win, 1 = draw, 0 = loss) rather than re-deriving them from the
    -- result string, removing the duplicated win/draw/loss logic.
    select
        group_letter,
        home_team as team_name,
        1 as played,
        case when home_points = 3 then 1 else 0 end as won,
        case when home_points = 1 then 1 else 0 end as drawn,
        case when home_points = 0 then 1 else 0 end as lost,
        home_score as gf,
        away_score as ga,
        home_points as points
    from group_results

    union all

    -- one row per team appearance (away side)
    select
        group_letter,
        away_team as team_name,
        1 as played,
        case when away_points = 3 then 1 else 0 end as won,
        case when away_points = 1 then 1 else 0 end as drawn,
        case when away_points = 0 then 1 else 0 end as lost,
        away_score as gf,
        home_score as ga,
        away_points as points
    from group_results

),

aggregated as (

    select
        group_letter,
        team_name,
        sum(played) as played,
        sum(won) as won,
        sum(drawn) as drawn,
        sum(lost) as lost,
        sum(gf) as gf,
        sum(ga) as ga,
        sum(gf) - sum(ga) as gd,
        sum(points) as points
    from per_team
    group by group_letter, team_name

)

select
    *,
    -- FIX 5: team_name is appended as a final, deterministic tiebreaker so two
    -- teams equal on points/gd/gf get a stable order that does not flip between
    -- runs. (FIFA criteria 4-8 -- head-to-head and fair-play -- remain
    -- documented-but-unimplemented above.)
    row_number() over (
        partition by group_letter
        order by points desc, gd desc, gf desc, team_name asc
    ) as rank
from aggregated
