-- Grain: one row per team. Aggregates fct_result across home and away
-- appearances into tournament-level totals.
-- stage_reached is best-effort ('group') in this phase: knockout progression
-- requires bracket resolution not yet modelled.

with results as (

    select *
    from {{ ref('fct_result') }}

),

per_appearance as (

    select
        home_team_key as team_key,
        home_score    as gf,
        away_score    as ga,
        case when result = 'home_win' then 1 else 0 end as win,
        case when result = 'draw' then 1 else 0 end     as draw,
        case when result = 'away_win' then 1 else 0 end as loss,
        case when result = 'home_win' then 3 when result = 'draw' then 1 else 0 end as points
    from results

    union all

    select
        away_team_key as team_key,
        away_score    as gf,
        home_score    as ga,
        case when result = 'away_win' then 1 else 0 end as win,
        case when result = 'draw' then 1 else 0 end     as draw,
        case when result = 'home_win' then 1 else 0 end as loss,
        case when result = 'away_win' then 3 when result = 'draw' then 1 else 0 end as points
    from results

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
    'group'                as stage_reached
from per_appearance
where team_key is not null
group by team_key
