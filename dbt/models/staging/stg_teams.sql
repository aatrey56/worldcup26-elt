-- Grain: one row per real team (country) appearing in the schedule.
-- Built from the union of home/away teams in stg_schedule, EXCLUDING
-- placeholder knockout slots. Left joins stg_matches to attach an API
-- team_id and the FIFA three-letter code (tla) when the team has been seen
-- in the fixtures or standings feed (else null).

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

api_attrs as (

    -- collapse home and away appearances into one id + fifa_code per team_name.
    -- The fifa_code (tla) can come from either the fixtures feed or the
    -- standings feed; max() picks the single non-null code per team.
    select
        team_name,
        max(team_id) as team_id,
        max(team_tla) as fifa_code
    from (
        select
            home_team as team_name,
            home_team_id as team_id,
            home_team_tla as team_tla
        from {{ ref('stg_matches') }}
        union all
        select
            away_team as team_name,
            away_team_id as team_id,
            away_team_tla as team_tla
        from {{ ref('stg_matches') }}
        union all
        select
            team_name,
            team_id,
            team_tla
        from {{ ref('stg_standings') }}
    )
    group by team_name

)

select
    t.team_name,
    a.team_id,
    a.fifa_code
from distinct_teams as t
left join api_attrs as a
    on t.team_name = a.team_name
