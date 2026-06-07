-- Grain: one row per FINISHED match.
-- Built as a normal TABLE in this phase (NOT incremental; that conversion
-- happens in a later phase). match_key is obtained by joining
-- int_results_scored to dim_match on the (home_team, away_team) name pair.

with results as (

    select *
    from {{ ref('int_results_scored') }}

),

matches as (

    select match_key, match_no
    from {{ ref('dim_match') }}

),

teams as (

    select team_key, team_name
    from {{ ref('dim_team') }}

)

select
    m.match_key,
    ht.team_key                                as home_team_key,
    awt.team_key                               as away_team_key,
    r.home_score,
    r.away_score,
    r.result,
    case
        when r.result = 'home_win' then ht.team_key
        when r.result = 'away_win' then awt.team_key
        else null
    end                                        as winner_team_key,
    r.kickoff_utc                              as played_at,
    current_timestamp                          as loaded_at
from results r
left join matches m
    on r.match_no = m.match_no
left join teams ht
    on r.home_team = ht.team_name
left join teams awt
    on r.away_team = awt.team_name
