-- Grain: one row per (group_letter, team) recomputed from FINISHED group
-- matches in int_results_scored. Aggregates played/won/drawn/lost/gf/ga/gd/
-- points, then ranks within each group.
--
-- LIVE EXCLUSION: only finished matches move the table, so in-play FIFA rows
-- (is_live = true) are excluded here. A live score therefore shows on the
-- dashboard (via fct_result) but does not alter the standings until full time,
-- which keeps ranks/qualification deterministic mid-match.
--
-- TIEBREAKER: the official FIFA World Cup 2026 group ranking (Art. 13). Teams
-- level on points are split FIRST by head-to-head, THEN by overall goals. The
-- 2026 regulations moved head-to-head ahead of overall goal difference (a change
-- from previous World Cups). Full order:
--   1. points (all group matches)
--   2. head-to-head points (matches among the teams still level)   } "step one"
--   3. head-to-head goal difference                                }
--   4. head-to-head goals scored                                   }
--   5. overall goal difference (all group matches)                 } "step two"
--   6. overall goals scored (all group matches)                    }
--   7. team conduct score (yellow/red cards)  -- NOT ingested      }
--   8. FIFA/Coca-Cola Men's World Ranking (fifa_world_ranking seed) } "step three"
-- team_name is the final deterministic key so the order never flips between runs.
--
-- Criterion 7 (conduct/cards) is not ingested, so it is skipped; the seeded FIFA
-- ranking (criterion 8) resolves almost all remaining ties. The head-to-head
-- block is computed among the teams sharing a points total (a single pass): the
-- rare FIFA case where a 3-way tie is partially broken and head-to-head is then
-- RECOMPUTED among the still-level pair is not modelled (it would need recursion);
-- documented here as a known edge.

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

),

-- HEAD-TO-HEAD (FIFA step one). Restrict to matches played BETWEEN teams that
-- are level on points within the group: a match counts toward head-to-head only
-- when both sides share the same overall points total. Teams alone on their
-- points value get no head-to-head rows (they are already separated by points),
-- so their coalesced h2h values never affect the order.
h2h_matches as (

    select gr.*
    from group_results as gr
    inner join aggregated as ah
        on gr.group_letter = ah.group_letter and gr.home_team = ah.team_name
    inner join aggregated as aa
        on gr.group_letter = aa.group_letter and gr.away_team = aa.team_name
    where ah.points = aa.points

),

h2h_per_team as (

    select
        group_letter,
        home_team as team_name,
        home_points as pts,
        home_score as gf,
        away_score as ga
    from h2h_matches
    union all
    select
        group_letter,
        away_team as team_name,
        away_points as pts,
        away_score as gf,
        home_score as ga
    from h2h_matches

),

h2h_agg as (

    select
        group_letter,
        team_name,
        sum(pts) as h2h_points,
        sum(gf) - sum(ga) as h2h_gd,
        sum(gf) as h2h_gf
    from h2h_per_team
    group by group_letter, team_name

),

fifa as (

    select
        team_name,
        fifa_rank
    from {{ ref('fifa_world_ranking') }}

)

select
    a.group_letter,
    a.team_name,
    a.played,
    a.won,
    a.drawn,
    a.lost,
    a.gf,
    a.ga,
    a.gd,
    a.points,
    f.fifa_rank,
    row_number() over (
        partition by a.group_letter
        order by
            a.points desc,
            coalesce(h.h2h_points, 0) desc,
            coalesce(h.h2h_gd, 0) desc,
            coalesce(h.h2h_gf, 0) desc,
            a.gd desc,
            a.gf desc,
            -- conduct score (cards) would sit here; not ingested, so skipped
            f.fifa_rank asc nulls last,
            a.team_name asc
    ) as rank
from aggregated as a
left join h2h_agg as h
    on a.group_letter = h.group_letter and a.team_name = h.team_name
left join fifa as f
    on a.team_name = f.team_name
