-- Grain: one row per team (team_id) that has taken or faced at least one shot.
-- Attacking aggregates (shots, goals, total_xg, finishing) come from the team's
-- own shots in fct_shot. xg_against is the total xG of shots taken AGAINST the
-- team: within each match, a shot's opponent is the other team_id seen in that
-- match, so we self-join fct_shot on match_id with a different team_id and sum the
-- opponents' xG per team. This is robust to the normal two-team match (and to any
-- stray multi-team artifact, since it simply sums every non-self shot in the
-- match). Empty-safe; teams with only defensive exposure still appear via the
-- full outer union of attack and defence. NO SELECT *.

with shots as (

    select
        match_id,
        team_id,
        is_goal,
        xg
    from {{ ref('fct_shot') }}

),

attack as (

    select
        team_id,
        count(*) as shots,
        sum(case when is_goal then 1 else 0 end) as goals,
        sum(coalesce(xg, 0.0)) as total_xg
    from shots
    group by team_id

),

defence as (

    -- xG conceded: for each team, sum the xG of every shot in its matches taken
    -- by a different team (the opponent).
    select
        own.team_id,
        sum(coalesce(opp.xg, 0.0)) as xg_against,
        sum(case when opp.is_goal then 1 else 0 end) as goals_against
    from shots as own
    inner join shots as opp
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
