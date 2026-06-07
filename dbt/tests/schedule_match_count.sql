-- Fails (returns a row) if dim_match does not have exactly 104 matches,
-- or does not have exactly 72 group-stage matches.

with counts as (
    select
        count(*)                                                  as total_matches,
        count(*) filter (where stage = 'group')                   as group_matches
    from {{ ref('dim_match') }}
)

select *
from counts
where total_matches != 104
   or group_matches != 72
