-- FIX 1: alert on silent data loss.
-- fct_result drops any finished, fully-scored result whose fixture_id does not
-- reconcile to a dim_match row (null match_key), because delete+insert cannot
-- dedupe on a null key. That drop is correct defensively, but a real result
-- vanishing must NOT be silent. This singular test RETURNS ROWS (fails) when a
-- FINISHED, fully-scored match in int_results_scored has no matching dim_match
-- (its fixture_id is absent from dim_match.match_id), so a mapping gap fails the
-- build loudly instead of quietly losing the result.

with scored as (

    select fixture_id
    from {{ ref('int_results_scored') }}

),

mapped as (

    select match_id
    from {{ ref('dim_match') }}
    where match_id is not null

)

select s.fixture_id
from scored s
left join mapped m
    on s.fixture_id = m.match_id
where m.match_id is null
