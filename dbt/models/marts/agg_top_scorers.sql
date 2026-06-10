-- Grain: one row per player in the FIFA season top-scorers feed (the golden
-- boot race). Sourced from stg_fifa_topscorers, left joined to dim_fifa_team so
-- each scorer's team_id resolves to a readable team_name (FIFA id system).
-- assists is carried through from the feed. Ordered by goals desc, then assists
-- desc, with player_name as a deterministic final tiebreak. Empty-safe:
-- pre-tournament the feed has 0 rows so this mart is empty.

with scorers as (

    select
        rank,
        player_id,
        player_name,
        team_id,
        goals,
        assists
    from {{ ref('stg_fifa_topscorers') }}

),

teams as (

    select
        team_id,
        team_name
    from {{ ref('dim_fifa_team') }}

)

select
    s.rank,
    s.player_id,
    s.player_name,
    s.team_id,
    t.team_name,
    s.goals,
    s.assists
from scorers as s
left join teams as t
    on s.team_id = t.team_id
order by s.goals desc, s.assists desc, s.player_name asc
