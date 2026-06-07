-- Grain: one row per real team (country) appearing in the schedule.
-- Built from the union of home/away teams in stg_schedule, EXCLUDING
-- placeholder knockout slots. Left joins stg_matches to attach an API
-- team_id when the team has been seen in the fixtures feed (else null).

with schedule_teams as (

    select home_team as team_name
    from {{ ref('stg_schedule') }}
    where not is_placeholder

    union

    select away_team as team_name
    from {{ ref('stg_schedule') }}
    where not is_placeholder

),

distinct_teams as (

    select distinct team_name
    from schedule_teams

),

api_ids as (

    -- collapse home and away appearances into one id per team_name
    select team_name, max(team_id) as team_id
    from (
        select home_team as team_name, home_team_id as team_id from {{ ref('stg_matches') }}
        union all
        select away_team as team_name, away_team_id as team_id from {{ ref('stg_matches') }}
    )
    group by team_name

)

select
    t.team_name,
    a.team_id
from distinct_teams t
left join api_ids a
    on t.team_name = a.team_name
