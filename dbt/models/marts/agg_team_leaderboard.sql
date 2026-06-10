-- Grain: one row per real team (all 48), the best-performing-teams board on the
-- football-data side. Driven by a LEFT JOIN from dim_team so EVERY team appears
-- even pre-tournament (the board is never empty); per-team tournament stats come
-- from agg_team_tournament and the group rank/qualification from
-- fct_group_standings. Stats coalesce to 0 for teams with no finished matches
-- yet. overall_rank is a deterministic ranking over points desc, gd desc,
-- gf desc, then team_name as a stable final tiebreak (so ranks do not flip
-- between runs and pre-tournament every team is tied at 0 and ordered by name).

with teams as (

    select
        team_key,
        team_name,
        fifa_code,
        group_letter
    from {{ ref('dim_team') }}

),

tournament as (

    select
        team_key,
        matches_played,
        wins,
        draws,
        losses,
        gf,
        ga,
        gd,
        points,
        stage_reached
    from {{ ref('agg_team_tournament') }}

),

standings as (

    select
        team_key,
        rank as group_rank,
        qualified_flag
    from {{ ref('fct_group_standings') }}

),

joined as (

    select
        t.team_key,
        t.team_name,
        t.fifa_code,
        t.group_letter,
        coalesce(a.matches_played, 0) as matches_played,
        coalesce(a.wins, 0) as wins,
        coalesce(a.draws, 0) as draws,
        coalesce(a.losses, 0) as losses,
        coalesce(a.gf, 0) as gf,
        coalesce(a.ga, 0) as ga,
        coalesce(a.gd, 0) as gd,
        coalesce(a.points, 0) as points,
        s.group_rank,
        coalesce(s.qualified_flag, false) as qualified_flag,
        coalesce(a.stage_reached, 'group') as stage_reached
    from teams as t
    left join tournament as a
        on t.team_key = a.team_key
    left join standings as s
        on t.team_key = s.team_key

)

select
    team_key,
    team_name,
    fifa_code,
    group_letter,
    matches_played,
    wins,
    draws,
    losses,
    gf,
    ga,
    gd,
    points,
    group_rank,
    qualified_flag,
    stage_reached,
    row_number() over (
        order by points desc, gd desc, gf desc, team_name asc
    ) as overall_rank
from joined
