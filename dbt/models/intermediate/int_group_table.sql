-- Grain: one row per (group_letter, team) recomputed from finished group
-- matches in int_results_scored. Aggregates played/won/drawn/lost/gf/ga/gd/
-- points, then ranks within each group.
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
    where group_letter is not null

),

per_team as (

    -- one row per team appearance (home side)
    select
        group_letter,
        home_team as team_name,
        1                                          as played,
        case when result = 'home_win' then 1 else 0 end as won,
        case when result = 'draw' then 1 else 0 end as drawn,
        case when result = 'away_win' then 1 else 0 end as lost,
        home_score                                 as gf,
        away_score                                 as ga,
        home_points                                as points
    from group_results

    union all

    -- one row per team appearance (away side)
    select
        group_letter,
        away_team as team_name,
        1                                          as played,
        case when result = 'away_win' then 1 else 0 end as won,
        case when result = 'draw' then 1 else 0 end as drawn,
        case when result = 'home_win' then 1 else 0 end as lost,
        away_score                                 as gf,
        home_score                                 as ga,
        away_points                                as points
    from group_results

),

aggregated as (

    select
        group_letter,
        team_name,
        sum(played)            as played,
        sum(won)               as won,
        sum(drawn)             as drawn,
        sum(lost)              as lost,
        sum(gf)                as gf,
        sum(ga)                as ga,
        sum(gf) - sum(ga)      as gd,
        sum(points)            as points
    from per_team
    group by group_letter, team_name

)

select
    *,
    row_number() over (
        partition by group_letter
        order by points desc, gd desc, gf desc
    ) as rank
from aggregated
