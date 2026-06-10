-- Grain: one row per player (player_id) who has taken at least one shot.
-- An xG leaderboard: shots, goals, total xG, xG per shot, and finishing
-- (goals - total_xg, i.e. over/under-performance vs expectation). Names come from
-- dim_fifa_player (lineups + top-scorers fallback). Penalty xG uses the empirical
-- constant from fct_shot; shots with null xG (open-play, no coordinates) count
-- toward shots/goals but contribute 0 to total_xg via coalesce, so the leaderboard
-- is still well defined when geometry is missing. Empty-safe. NO SELECT *.

with shots as (

    select
        player_id,
        team_id,
        is_goal,
        xg
    from {{ ref('fct_shot') }}

),

players as (

    select
        player_id,
        player_name,
        position,
        team_id
    from {{ ref('dim_fifa_player') }}

),

by_player as (

    select
        player_id,
        max(team_id) as team_id,
        count(*) as shots,
        sum(case when is_goal then 1 else 0 end) as goals,
        sum(coalesce(xg, 0.0)) as total_xg
    from shots
    group by player_id

)

select
    bp.player_id,
    p.player_name,
    p.position,
    -- prefer the dimension's coherent team over the per-shot max (consistency)
    coalesce(p.team_id, bp.team_id) as team_id,
    bp.shots,
    bp.goals,
    bp.total_xg,
    bp.total_xg / nullif(bp.shots, 0) as xg_per_shot,
    bp.goals - bp.total_xg as finishing
from by_player as bp
left join players as p
    on bp.player_id = p.player_id
order by bp.goals desc, bp.total_xg desc
