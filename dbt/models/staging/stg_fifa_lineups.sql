-- Grain: one row per player appearance in a match lineup (raw.fifa_lineups).
-- A clean 1:1 projection of the FIFA lineup player object landed by the loader.
-- player_name comes from FIFA's localized list ([{Locale, Description}]), so we
-- read [0].Description. position_code is FIFA's integer position
-- (0=goalkeeper, 1=defender, 2=midfielder, 3=forward; 4=bench/no position),
-- mapped to a readable position label. Empty pre-tournament (no played matches).
-- COUPLING NOTE: assumes the api.fifa.com v3 live-endpoint lineup player shape.

with src as (

    select * from {{ source('raw', 'fifa_lineups') }}

),

extracted as (

    select
        player_id,
        match_id,
        payload ->> '$.PlayerName[0].Description' as player_name,
        payload ->> '$.ShortName[0].Description' as short_name,
        cast(payload ->> '$.IdTeam' as bigint) as team_id,
        cast(payload ->> '$.Position' as int) as position_code,
        loaded_at
    from src

)

select
    player_id,
    match_id,
    player_name,
    short_name,
    team_id,
    position_code,
    case position_code
        when 0 then 'Goalkeeper'
        when 1 then 'Defender'
        when 2 then 'Midfielder'
        when 3 then 'Forward'
    end as position,
    loaded_at
from extracted
