-- Grain: one row per scheduled match (exactly 104), keyed by match_no/match_key.
-- home_team_key / away_team_key are NULL for placeholder knockout slots
-- (we only join dim_team for real country names). match_id is the API
-- fixture id, sourced from int_match_map by match_no (a stable id-based
-- reconciliation that works for both group and knockout rows). It is null
-- when the match has not yet been seen in the fixtures feed.

with schedule as (

    select *
    from {{ ref('stg_schedule') }}

),

match_map as (

    select fixture_id, match_no
    from {{ ref('int_match_map') }}

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
    mm.fixture_id       as match_id,
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
left join match_map mm
    on s.match_no = mm.match_no
