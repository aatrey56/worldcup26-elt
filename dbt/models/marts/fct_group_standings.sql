-- Grain: one row per (group_letter, team). Sourced from the recomputed
-- int_group_table, joined to dim_team for the team surrogate key.
--
-- FIX 5: qualification for the 2026 format. 32 of 48 teams advance:
--   the top 2 of every group (24 teams), PLUS the 8 best third-placed teams
--   across all 12 groups. The 8 best thirds are ranked across groups by
--   points DESC, then goal_difference DESC, then goals_for DESC; the top 8
--   qualify. qualified_flag is therefore true when rank <= 2, OR rank = 3 and
--   the team is in that top-8 of thirds.
-- NOTE: this is only fully correct once the group stage completes. With
-- partial data the best-third ranking is over whatever thirds exist so far,
-- so it is best-effort mid-tournament, but the qualification LOGIC is correct.

with standings as (

    select *
    from {{ ref('int_group_table') }}

),

teams as (

    select team_key, team_name
    from {{ ref('dim_team') }}

),

best_thirds as (

    -- rank the third-placed team of each group across all groups; top 8 qualify
    select
        group_letter,
        team_name,
        row_number() over (
            order by points desc, gd desc, gf desc
        ) as third_rank
    from standings
    where rank = 3

)

select
    s.group_letter,
    t.team_key,
    s.played,
    s.won,
    s.drawn,
    s.lost,
    s.gf,
    s.ga,
    s.gd,
    s.points,
    s.rank,
    (
        s.rank <= 2
        or (s.rank = 3 and bt.third_rank is not null and bt.third_rank <= 8)
    ) as qualified_flag
from standings s
left join teams t
    on s.team_name = t.team_name
left join best_thirds bt
    on s.group_letter = bt.group_letter
   and s.team_name = bt.team_name
