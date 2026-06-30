-- Grain: one row per (group_letter, team). The LIVE standings table that powers
-- the groups page: provisional standings "as things stand" (in-play matches
-- folded in) from int_group_table_live, joined to dim_team for the surrogate key
-- and fifa_code.
--
-- This sits alongside fct_group_standings (the OFFICIAL, finished-only table with
-- qualified_flag). The page renders this live version: a team currently playing
-- shows a status circle (winning/tied/losing), its live score, and its
-- provisional points; teams re-rank on the provisional points. When no group
-- match is in play, every is_playing is false and this equals the official table.

with standings as (

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
        live_status,
        fifa_rank,
        rank
    from {{ ref('int_group_table_live') }}

),

teams as (

    select
        team_key,
        team_name,
        fifa_code
    from {{ ref('dim_team') }}

)

select
    s.group_letter,
    t.team_key,
    t.fifa_code,
    s.played,
    s.won,
    s.drawn,
    s.lost,
    s.gf,
    s.ga,
    s.gd,
    s.points,
    s.is_playing,
    s.points_live_delta,
    s.live_for,
    s.live_against,
    s.live_status,
    s.fifa_rank,
    s.rank
from standings as s
left join teams as t
    on s.team_name = t.team_name
