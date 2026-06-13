-- Grain: one row per (group_letter, team) over ALL 48 group-stage teams, with
-- PROVISIONAL standings that count an in-play match "as things stand".
--
-- DIFFERENCE FROM int_group_table: that model is the OFFICIAL table - it counts
-- finished matches only (is_live = false), so the standings never move until a
-- game ends. THIS model is the LIVE table - it ALSO folds in the current score
-- of an in-play match, so a team currently winning provisionally gains 3 points,
-- a draw 1, a loss 0, and the table re-ranks "as things stand". int_results_scored
-- already derives home_points/away_points from the live score for is_live rows,
-- so summing finished + live points yields the provisional total directly.
--
-- ALL 48 TEAMS: unlike int_group_table (which only lists teams that have a
-- result), this left-joins from dim_team so every group always has its 4 teams,
-- even at 0 games played. That guarantees each group has a determinate 3rd place,
-- which the projected-bracket resolver (resolve_bracket.py) requires to rank the
-- 12 third-placed teams.
--
-- LIVE EXTRAS (for the standings page): is_playing flags a team currently in an
-- in-play match; live_status is winning/tied/losing from that match's current
-- score; live_for/live_against are that score from the team's perspective;
-- points_live_delta is the 3/1/0 the in-play match is currently contributing
-- (so the page can show "+3 as things stand"). A team not currently playing has
-- is_playing = false and null live_* fields.
--
-- TIEBREAK: same first-three official criteria as int_group_table (points, goal
-- difference, goals for) with team_name as the deterministic final tiebreaker.
-- Head-to-head / fair-play (FIFA criteria 4+) are not implemented here either.

with group_results as (

    select
        group_letter,
        home_team,
        away_team,
        home_score,
        away_score,
        home_points,
        away_points,
        is_live
    from {{ ref('int_results_scored') }}
    where group_letter is not null

),

per_team as (

    -- one row per team appearance (home side)
    select
        group_letter,
        home_team as team_name,
        1 as played,
        case when home_points = 3 then 1 else 0 end as won,
        case when home_points = 1 then 1 else 0 end as drawn,
        case when home_points = 0 then 1 else 0 end as lost,
        home_score as gf,
        away_score as ga,
        home_points as points,
        is_live,
        case when is_live then home_points end as live_points,
        case when is_live then home_score end as live_for,
        case when is_live then away_score end as live_against
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
        away_points as points,
        is_live,
        case when is_live then away_points end as live_points,
        case when is_live then away_score end as live_for,
        case when is_live then home_score end as live_against
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
        sum(points) as points,
        bool_or(is_live) as is_playing,
        -- a team has at most one in-play match, so max() picks that match's
        -- values (all other appearances contribute null to these columns).
        max(live_points) as live_points,
        max(live_for) as live_for,
        max(live_against) as live_against
    from per_team
    group by group_letter, team_name

),

all_teams as (

    select
        group_letter,
        team_name
    from {{ ref('dim_team') }}
    where group_letter is not null

),

filled as (

    -- every group-stage team appears, defaulting to a 0-match row
    select
        t.group_letter,
        t.team_name,
        coalesce(a.played, 0) as played,
        coalesce(a.won, 0) as won,
        coalesce(a.drawn, 0) as drawn,
        coalesce(a.lost, 0) as lost,
        coalesce(a.gf, 0) as gf,
        coalesce(a.ga, 0) as ga,
        coalesce(a.gd, 0) as gd,
        coalesce(a.points, 0) as points,
        coalesce(a.is_playing, false) as is_playing,
        coalesce(a.live_points, 0) as points_live_delta,
        a.live_for,
        a.live_against
    from all_teams as t
    left join aggregated as a
        on
            t.group_letter = a.group_letter
            and t.team_name = a.team_name

)

select
    group_letter,
    team_name,
    played,
    won,
    drawn,
    lost,
    gf,
    ga,
    gd,
    points,
    is_playing,
    points_live_delta,
    live_for,
    live_against,
    case
        when not is_playing then null
        when live_for > live_against then 'winning'
        when live_for = live_against then 'tied'
        else 'losing'
    end as live_status,
    row_number() over (
        partition by group_letter
        order by points desc, gd desc, gf desc, team_name asc
    ) as rank
from filled
