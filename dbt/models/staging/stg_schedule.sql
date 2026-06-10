-- Grain: one row per scheduled match (104 rows, from the authoritative seed).
-- Staging is 1:1 with the seed: rename, cast, clean only. The one derived
-- column is is_placeholder, a structural flag (not business logic) marking
-- knockout rows whose teams are not yet real countries.

with src as (

    select * from {{ ref('schedule_seed') }}

),

cleaned as (

    select
        cast(match_no as integer) as match_no,
        cast(date as date) as match_date,
        cast(kickoff_et as varchar) as kickoff_et,
        cast(home_team as varchar) as home_team,
        cast(away_team as varchar) as away_team,
        cast(stage as varchar) as stage,
        cast(round_label as varchar) as round_label,
        cast(city as varchar) as city,
        cast(venue as varchar) as venue,
        cast(channel_en as varchar) as channel_en,
        cast(channel_es as varchar) as channel_es,
        nullif(cast(group_letter as varchar), '') as group_letter
    from src

)

select
    *,
    (
        home_team like 'Winner%' or home_team like 'Runner-up%'
        or home_team like '3rd%' or home_team = 'TBD'
        or away_team like 'Winner%' or away_team like 'Runner-up%'
        or away_team like '3rd%' or away_team = 'TBD'
    ) as is_placeholder
from cleaned
