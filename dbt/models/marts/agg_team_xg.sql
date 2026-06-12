-- Grain: one row per team (team_id) that has taken or faced at least one shot.
-- Attacking aggregates (shots, goals, total_xg, finishing) come from the team's
-- own shots in fct_shot. xg_against is the total xG of shots taken AGAINST the
-- team: within each match, a shot's opponent is the other team_id seen in that
-- match. We first roll fct_shot up to one row per (match_id, team_id) with that
-- team's xG and goals in the match, THEN self-join those per-match-team totals
-- on match_id with a different team_id. Aggregating before the join is essential:
-- joining at the raw-shot grain would multiply each opponent's xG by the team's
-- OWN shot count (a cross product), inflating xg_against (e.g. an 18-shot team
-- would count the opponent's xG 18 times). Empty-safe; teams with only defensive
-- exposure still appear via the union of attack and defence. NO SELECT *.

with shots as (

    select
        match_id,
        team_id,
        is_goal,
        xg
    from {{ ref('fct_shot') }}

),

match_team as (

    -- one row per (match, team): that team's xG and goals in that match.
    select
        match_id,
        team_id,
        count(*) as shots,
        sum(case when is_goal then 1 else 0 end) as goals,
        sum(coalesce(xg, 0.0)) as total_xg
    from shots
    group by match_id, team_id

),

attack as (

    select
        team_id,
        sum(shots) as shots,
        sum(goals) as goals,
        sum(total_xg) as total_xg
    from match_team
    group by team_id

),

defence as (

    -- xG conceded: for each team, sum the opponent's per-match xG/goals across
    -- the team's matches. The join is on the per-match-team rollup (match_team),
    -- so each (match, opponent) contributes exactly once - no shot-count blow-up.
    select
        own.team_id,
        sum(opp.total_xg) as xg_against,
        sum(opp.goals) as goals_against
    from match_team as own
    inner join match_team as opp
        on
            own.match_id = opp.match_id
            and own.team_id != opp.team_id
    group by own.team_id

),

team_ids as (

    select team_id from attack
    union
    select team_id from defence

)

select
    t.team_id,
    coalesce(a.shots, 0) as shots,
    coalesce(a.goals, 0) as goals,
    coalesce(a.total_xg, 0.0) as total_xg,
    coalesce(a.goals, 0) - coalesce(a.total_xg, 0.0) as finishing,
    coalesce(d.xg_against, 0.0) as xg_against,
    coalesce(d.goals_against, 0) as goals_against
from team_ids as t
left join attack as a
    on t.team_id = a.team_id
left join defence as d
    on t.team_id = d.team_id
order by total_xg desc
