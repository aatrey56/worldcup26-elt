-- Grain: one row per venue (distinct venue + city).

with venues as (

    select
        venue_name,
        city
    from {{ ref('stg_venues') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['venue_name', 'city']) }} as venue_key,
    cast(null as bigint) as venue_id,
    venue_name,
    city,
    cast(null as varchar) as country,
    cast(null as integer) as capacity
from venues
