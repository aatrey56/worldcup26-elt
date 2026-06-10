-- Grain: one row per FIFA team (team_id) seen in the FIFA calendar feed.
-- The FIFA-side team dimension: it lets FIFA shot/xG/top-scorer marts show a
-- readable team name for a team_id. Built by unioning both sides of every
-- match in stg_fifa_matches into (team_id, team_name) pairs, then deduping to
-- ONE COHERENT row per team_id (a single picked row via row_number, NOT an
-- independent max() per column, so the name always belongs to the same source
-- pairing). We prefer a non-null name and the most recent match.
--
-- This is the FIFA id system, which deliberately does NOT join to the
-- football-data dim_team (team_id != seed team name); both sides keep their
-- own readable names. Empty-safe: with no FIFA matches this is an empty
-- dimension and nothing errors.

with match_sides as (

    select
        home_team_id as team_id,
        home_team_name as team_name,
        match_id
    from {{ ref('stg_fifa_matches') }}
    where home_team_id is not null

    union all

    select
        away_team_id as team_id,
        away_team_name as team_name,
        match_id
    from {{ ref('stg_fifa_matches') }}
    where away_team_id is not null

),

dedup as (

    select
        team_id,
        team_name,
        row_number() over (
            partition by team_id
            order by
                (team_name is not null) desc,
                match_id desc
        ) as rn
    from match_sides

)

select
    team_id,
    team_name
from dedup
where rn = 1
