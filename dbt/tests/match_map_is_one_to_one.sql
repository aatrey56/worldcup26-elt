-- Asserts int_match_map is a 1:1 mapping: no fixture_id maps to more than one
-- match_no, and no match_no maps to more than one fixture_id. Returns a row
-- (fails) for any violation. It deliberately does NOT assert an exact row count,
-- so it passes on the 5-row sample as well as the 104-row live feed.

with fixture_dupes as (

    select fixture_id as id, count(*) as n
    from {{ ref('int_match_map') }}
    group by fixture_id
    having count(*) > 1

),

match_no_dupes as (

    select match_no as id, count(*) as n
    from {{ ref('int_match_map') }}
    group by match_no
    having count(*) > 1

)

select id, n from fixture_dupes
union all
select id, n from match_no_dupes
