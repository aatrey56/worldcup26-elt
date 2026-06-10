-- Grain: one row per team. Aggregates fct_result across home and away
-- appearances into tournament-level totals.
--
-- FIX 3/8: stage_reached is the FURTHEST stage a team actually reached,
-- computed from fct_result joined to dim_match.stage. Stages are ranked by a
-- STRICTLY DISTINCT tournament order so the label is deterministic:
--   group(1) < r32(2) < r16(3) < qf(4) < sf(5) < third(6) < final(7).
-- 'third' and 'sf' previously shared order 5, which made max_by non-
-- deterministic for semi-final losers (it could return either label for the
-- same max order). With distinct orders, a team that played the third-place
-- match deterministically shows 'third' (order 6 > sf's 5), and the two
-- finalists deterministically show 'final' (order 7). We pick the label by the
-- single max stage_order, so there are no ties to break. A team with no
-- finished matches yet defaults to 'group'.

with results as (

    select *
    from {{ ref('fct_result') }}

),

match_stage as (

    select match_key, stage
    from {{ ref('dim_match') }}

),

results_staged as (

    select r.*, m.stage
    from results r
    left join match_stage m
        on r.match_key = m.match_key

),

per_appearance as (

    select
        home_team_key as team_key,
        stage,
        home_score    as gf,
        away_score    as ga,
        case when result = 'home_win' then 1 else 0 end as win,
        case when result = 'draw' then 1 else 0 end     as draw,
        case when result = 'away_win' then 1 else 0 end as loss,
        case when result = 'home_win' then 3 when result = 'draw' then 1 else 0 end as points
    from results_staged

    union all

    select
        away_team_key as team_key,
        stage,
        away_score    as gf,
        home_score    as ga,
        case when result = 'away_win' then 1 else 0 end as win,
        case when result = 'draw' then 1 else 0 end     as draw,
        case when result = 'home_win' then 1 else 0 end as loss,
        case when result = 'away_win' then 3 when result = 'draw' then 1 else 0 end as points
    from results_staged

),

ranked as (

    select
        *,
        case stage
            when 'group' then 1
            when 'r32'   then 2
            when 'r16'   then 3
            when 'qf'    then 4
            when 'sf'    then 5
            when 'third' then 6
            when 'final' then 7
            else 1
        end as stage_order
    from per_appearance

)

select
    team_key,
    count(*)               as matches_played,
    sum(win)               as wins,
    sum(draw)              as draws,
    sum(loss)              as losses,
    sum(gf)                as gf,
    sum(ga)                as ga,
    sum(gf) - sum(ga)      as gd,
    sum(points)            as points,
    coalesce(
        max_by(stage, stage_order),
        'group'
    )                      as stage_reached
from ranked
where team_key is not null
group by team_key
