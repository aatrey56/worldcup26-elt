-- Fails (returns rows) for any finished match in fct_result where the total
-- points awarded across both teams is not 3 (decisive) or 2 (draw).

with reconciled as (

    select
        match_key,
        result,
        case
            when result in ('home_win', 'away_win') then 3
            when result = 'draw' then 2
            else -1
        end as total_points
    from {{ ref('fct_result') }}

)

select *
from reconciled
where total_points not in (2, 3)
