-- FIX 1: alert on silent data loss.
-- fct_result drops any scored result whose match_no does not reconcile to a
-- dim_match row (null match_key), because delete+insert cannot dedupe on a null
-- key. That drop is correct defensively, but a real result vanishing must NOT be
-- silent. This singular test RETURNS ROWS (fails) when a scored match in
-- int_results_scored has no matching dim_match (its match_no is absent from
-- dim_match.match_no), so a mapping gap fails the build loudly instead of
-- quietly losing the result.
--
-- match_no is the source-agnostic reconciliation key, so this guards both
-- FIFA-sourced and football-data-sourced rows. (The previous fixture_id-based
-- join would have spuriously failed every FIFA-only row, whose fixture_id is
-- null.)

with scored as (

    select match_no
    from {{ ref('int_results_scored') }}

),

mapped as (

    select match_no
    from {{ ref('dim_match') }}
    where match_no is not null

)

select s.match_no
from scored s
left join mapped m
    on s.match_no = m.match_no
where m.match_no is null
