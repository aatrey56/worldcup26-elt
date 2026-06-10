-- Grain: one row per distinct (venue, city) pair in the schedule.

with src as (

    select distinct
        venue as venue_name,
        city
    from {{ ref('stg_schedule') }}

)

select
    venue_name,
    city
from src
