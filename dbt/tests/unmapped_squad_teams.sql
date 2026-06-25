-- DATA-QUALITY GATE: every Wikipedia squad team must reconcile to a real team.
--
-- stg_squads canonicalizes the Wikipedia country name to the seed name via the
-- wiki_team_name_crosswalk seed, and fct_squad_quality INNER joins that to
-- dim_team. If a squad's team_name fails to reconcile (a new Wikipedia spelling,
-- a missing crosswalk row), that whole team would be SILENTLY dropped from
-- fct_squad_quality. This test returns a row (fails the build) for any distinct
-- squad team_name that has no matching dim_team, so a crosswalk gap fails loudly
-- instead of quietly losing a team's squad-quality row.
--
-- Empty-safe: when the squads load degrades (stg_squads empty) there are no rows
-- to reconcile, so the test passes.

with squad_teams as (

    select distinct team_name
    from {{ ref('stg_squads') }}

)

select s.team_name
from squad_teams as s
left join {{ ref('dim_team') }} as d
    on s.team_name = d.team_name
where d.team_key is null
