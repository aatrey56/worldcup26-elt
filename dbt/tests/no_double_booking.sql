-- Fails (returns rows) if any team is booked in two different matches on the
-- same match_date. Unpivots home/away team_key and ignores null team keys.

with team_dates as (

    select match_key, match_date, home_team_key as team_key
    from {{ ref('dim_match') }}
    where home_team_key is not null

    union all

    select match_key, match_date, away_team_key as team_key
    from {{ ref('dim_match') }}
    where away_team_key is not null

)

select
    team_key,
    match_date,
    count(distinct match_key) as match_count
from team_dates
group by team_key, match_date
having count(distinct match_key) > 1
