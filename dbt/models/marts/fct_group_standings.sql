-- Grain: one row per (group_letter, team). Sourced from the recomputed
-- int_group_table, joined to dim_team for the team surrogate key.

with standings as (

    select *
    from {{ ref('int_group_table') }}

),

teams as (

    select team_key, team_name
    from {{ ref('dim_team') }}

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
    s.rank <= 2 as qualified_flag
from standings s
left join teams t
    on s.team_name = t.team_name
