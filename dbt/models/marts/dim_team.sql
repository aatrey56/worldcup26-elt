-- Grain: one row per real team (country).
-- group_letter is sourced from the schedule (a team's group-stage group).

with teams as (

    select team_name, team_id, fifa_code
    from {{ ref('stg_teams') }}

),

team_group as (

    -- a team's group letter: from any group-stage schedule row it appears in
    select team_name, max(group_letter) as group_letter
    from (
        select home_team as team_name, group_letter
        from {{ ref('stg_schedule') }}
        where not is_placeholder and group_letter is not null

        union all

        select away_team as team_name, group_letter
        from {{ ref('stg_schedule') }}
        where not is_placeholder and group_letter is not null
    )
    group by team_name

)

select
    {{ dbt_utils.generate_surrogate_key(['t.team_name']) }} as team_key,
    t.team_id,
    t.team_name,
    -- FIX 2: fifa_code (three-letter code, e.g. MEX, KOR) sourced from the API
    -- tla, flowed through stg_teams. Confederation remains null (not in feed).
    t.fifa_code,
    cast(null as varchar) as confederation,
    tg.group_letter,
    -- is_host: the crosswalk standardizes 'United States' -> 'USA', so only the
    -- canonical seed names are listed here.
    t.team_name in ('Mexico', 'Canada', 'USA') as is_host
from teams t
left join team_group tg
    on t.team_name = tg.team_name
