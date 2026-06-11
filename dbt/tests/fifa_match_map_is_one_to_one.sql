-- Asserts int_fifa_match_map is a 1:1 mapping: no fifa_match_id maps to more
-- than one match_no, and no match_no maps to more than one fifa_match_id.
-- Returns a row (fails) for any violation. It deliberately does NOT assert an
-- exact row count, so it passes whether FIFA has surfaced all 104 fixtures or
-- only a subset (and on the sample, which has no FIFA match-result rows).

with fixture_dupes as (

    select fifa_match_id as id, count(*) as n
    from {{ ref('int_fifa_match_map') }}
    group by fifa_match_id
    having count(*) > 1

),

match_no_dupes as (

    select match_no as id, count(*) as n
    from {{ ref('int_fifa_match_map') }}
    group by match_no
    having count(*) > 1

)

select cast(id as varchar) as id, n from fixture_dupes
union all
select cast(id as varchar) as id, n from match_no_dupes
