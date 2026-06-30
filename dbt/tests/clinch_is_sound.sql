-- Soundness guard for int_group_clinch (group-WINNER clinches).
--
-- int_group_clinch is head-to-head aware: a team can clinch its position without
-- being points-separated from below (e.g. it has beaten everyone who can still
-- match its points, so head-to-head keeps it ahead). So the old "must be
-- points-separated" check no longer applies.
--
-- What IS always true: a team that has clinched FIRST place cannot be capable of
-- being out-pointed by anyone. If any other team in the group can still reach
-- STRICTLY more points than the clinched leader's CURRENT points, then there is
-- a completion where that team finishes above it on points alone (points is the
-- first criterion, ahead of head-to-head), so the leader is NOT actually locked
-- as 1st and the clinch is a false positive. This recomputes points and the
-- remaining-game count directly from int_results_scored + the schedule,
-- independently of the python model, so it is a genuine cross-check. (It targets
-- position 1, the case the head-to-head logic newly confirms and the one the
-- bracket leans on; deeper positions are covered by the model's self_test.)

with finished as (

    select
        group_letter,
        home_team as team_name,
        home_points as points,
        1 as played
    from {{ ref('int_results_scored') }}
    where group_letter is not null and not is_live

    union all

    select
        group_letter,
        away_team as team_name,
        away_points as points,
        1 as played
    from {{ ref('int_results_scored') }}
    where group_letter is not null and not is_live

),

teams as (

    select
        group_letter,
        team_name
    from {{ ref('dim_team') }}
    where group_letter is not null

),

per_team as (

    select
        t.group_letter,
        t.team_name,
        coalesce(sum(f.points), 0) as points,
        coalesce(sum(f.played), 0) as played
    from teams as t
    left join finished as f
        on t.group_letter = f.group_letter and t.team_name = f.team_name
    group by t.group_letter, t.team_name

),

with_ceiling as (

    -- in a 4-team round robin each team plays 3 games; the most points still
    -- reachable is current points + 3 for every game not yet played.
    select
        group_letter,
        team_name,
        points,
        points + 3 * (3 - played) as max_reachable
    from per_team

),

clinched_first as (

    select
        group_letter,
        team_name
    from {{ ref('int_group_clinch') }}
    where is_clinched and position = 1

),

-- any other team in the group that can still strictly out-point the clinched
-- leader's CURRENT points is a violation: the leader could be caught on points,
-- so a "clinched 1st" flag would be a false positive.
violations as (

    select
        cf.group_letter,
        cf.team_name as clinched_first,
        leader.points as leader_points,
        other.team_name as challenger,
        other.max_reachable as challenger_ceiling
    from clinched_first as cf
    inner join with_ceiling as leader
        on cf.group_letter = leader.group_letter and cf.team_name = leader.team_name
    inner join with_ceiling as other
        on cf.group_letter = other.group_letter and cf.team_name != other.team_name
    where other.max_reachable > leader.points

)

select * from violations
