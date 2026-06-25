-- Grain: one row per squad player (team_name, player) from raw.squads, which is
-- landed from the Wikipedia "2026 FIFA World Cup squads" page by
-- include/extract/load_squads.py. Staging is 1:1 with the source: rename, clean,
-- and standardize the country name. The one added step is country-name
-- canonicalization: Wikipedia spells a few nations differently from the seed
-- (Turkey vs Turkiye, United States vs USA, Czech Republic vs Czechia, etc.), so
-- we map Wikipedia names to the seed's canonical names via the
-- wiki_team_name_crosswalk seed. Without this, the team_name join to dim_team in
-- fct_squad_quality would silently drop those nations.
-- Empty-safe: raw.squads is empty if the Wikipedia load failed/degraded.

with src as (

    select * from {{ source('raw', 'squads') }}

),

crosswalk as (

    select
        wiki_name,
        seed_name
    from {{ ref('wiki_team_name_crosswalk') }}

)

select
    coalesce(cw.seed_name, s.team_name) as team_name,
    s.player,
    s.club,
    s.position,
    s.loaded_at
from src as s
left join crosswalk as cw
    on s.team_name = cw.wiki_name
