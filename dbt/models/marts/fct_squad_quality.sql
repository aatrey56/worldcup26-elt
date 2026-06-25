-- Grain: one row per WC 2026 national team (joined to dim_team via team_key).
-- A "squad quality" context stat: how many of a team's players play club football
-- in a TOP-5 European league (Premier League, La Liga, Serie A, Bundesliga,
-- Ligue 1), plus squad size and the resulting percentage. Source is the
-- Wikipedia squad list (stg_squads); the club -> league mapping is the
-- top5_clubs seed (2025/26 rosters). A player counts as top-5 when their club
-- name matches a seed club. This is context only (e.g. Spain is stacked with
-- top-5 players yet drew 0-0 with Cape Verde), so it is excluded from results.
--
-- team_key is resolved by joining the crosswalk-canonicalized squad team_name to
-- dim_team. An INNER join to dim_team keeps the grain to the 48 real teams and
-- guarantees a non-null FK; a Wikipedia squad whose team_name fails to reconcile
-- (should not happen given the crosswalk) is dropped rather than emitted with a
-- null key. Empty-safe: stg_squads is empty if the squads load degraded.

with squads as (

    select
        team_name,
        club
    from {{ ref('stg_squads') }}

),

top5 as (

    select club
    from {{ ref('top5_clubs') }}

),

flagged as (

    select
        s.team_name,
        case when t.club is not null then 1 else 0 end as is_top5
    from squads as s
    left join top5 as t
        on s.club = t.club

),

per_team as (

    select
        team_name,
        count(*) as squad_size,
        sum(is_top5) as top5_count
    from flagged
    group by team_name

),

teams as (

    select
        team_key,
        team_name
    from {{ ref('dim_team') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['d.team_name']) }} as team_key,
    d.team_name,
    p.squad_size,
    p.top5_count,
    round(100.0 * p.top5_count / p.squad_size, 1) as top5_pct
from per_team as p
inner join teams as d
    on p.team_name = d.team_name
