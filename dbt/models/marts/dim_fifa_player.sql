-- Grain: one row per FIFA player (player_id).
-- The player dimension that lets xG leaderboards show names. Built by unioning
-- two name-bearing FIFA sources and deduping to one row per player:
--   * stg_fifa_lineups   - every named player in a match lineup (carries
--                          position); a player appears once per match, so we
--                          dedup across matches here.
--   * stg_fifa_topscorers - the season top-scorers feed; a fallback so a scorer
--                          who is not in the (sampled) lineups still gets a name.
-- Per player we coalesce to the first non-null name/team/position seen, preferring
-- the lineup source for position (top-scorers has no position). Empty-safe: with
-- no lineups or scorers this is an empty dimension and nothing errors.

with lineup_players as (

    select
        match_id,
        player_id,
        player_name,
        short_name,
        team_id,
        position,
        position_code
    from {{ ref('stg_fifa_lineups') }}

),

lineup_dedup as (

    -- One COHERENT row per player: instead of independent max() over each column
    -- (which can mix a name from one match with a team/position from another), we
    -- pick a single real lineup row per player, preferring the most complete and
    -- most recent appearance (position present, name present, latest match_id).
    select
        player_id,
        player_name,
        short_name,
        team_id,
        position,
        position_code
    from (
        select
            *,
            row_number() over (
                partition by player_id
                order by
                    (position is not null) desc,
                    (player_name is not null) desc,
                    match_id desc
            ) as rn
        from lineup_players
    ) as ranked
    where rn = 1

),

scorer_players as (

    select
        player_id,
        player_name,
        team_id
    from {{ ref('stg_fifa_topscorers') }}

),

all_player_ids as (

    select player_id from lineup_dedup
    union
    select player_id from scorer_players

)

select
    ids.player_id,
    coalesce(lu.player_name, sc.player_name) as player_name,
    lu.short_name,
    coalesce(lu.team_id, sc.team_id) as team_id,
    lu.position,
    lu.position_code,
    lu.player_id is not null as in_lineups,
    sc.player_id is not null as in_topscorers
from all_player_ids as ids
left join lineup_dedup as lu
    on ids.player_id = lu.player_id
left join scorer_players as sc
    on ids.player_id = sc.player_id
