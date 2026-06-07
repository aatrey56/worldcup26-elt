-- Grain: one row per scheduled match (exactly 104).
-- home_team_key / away_team_key are NULL for placeholder knockout slots
-- (we only join dim_team for real country names). match_id is the API
-- fixture id when the match has been seen in the fixtures feed (else null).

with schedule as (

    select *
    from {{ ref('stg_schedule') }}

),

matches as (

    select home_team, away_team, fixture_id
    from {{ ref('stg_matches') }}

),

teams as (

    select team_key, team_name
    from {{ ref('dim_team') }}

),

venues as (

    select venue_key, venue_name, city
    from {{ ref('dim_venue') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['s.match_no']) }} as match_key,
    s.match_no,
    m.fixture_id        as match_id,
    s.match_date,
    s.kickoff_et,
    s.stage,
    s.round_label,
    s.group_letter,
    ht.team_key         as home_team_key,
    awt.team_key        as away_team_key,
    v.venue_key,
    s.channel_en,
    s.channel_es
from schedule s
left join teams ht
    on s.home_team = ht.team_name and not s.is_placeholder
left join teams awt
    on s.away_team = awt.team_name and not s.is_placeholder
left join venues v
    on s.venue = v.venue_name and s.city = v.city
left join matches m
    on s.home_team = m.home_team and s.away_team = m.away_team
