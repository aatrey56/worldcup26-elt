-- Grain: one row per FINISHED match.
--
-- INCREMENTAL model. unique_key = match_key. Strategy = delete+insert, which
-- gives upsert (merge) semantics on DuckDB (DuckDB has no native MERGE): dbt
-- deletes the incoming match_keys from the target, then inserts the new rows,
-- so a corrected score replaces its existing row and never duplicates it.
--
-- Incremental predicate: on incremental runs we only pull source rows whose
-- raw load timestamp is newer than the newest one already loaded. Because the
-- loader stamps a fresh loaded_at whenever a fixture is (re)landed, this picks
-- up BOTH brand-new finished matches AND corrections to already-loaded scores,
-- while skipping rows that have not changed. On the first run the table does
-- not exist, so is_incremental() is false and every finished match is loaded.
--
-- match_key is obtained by joining int_results_scored to dim_match on the
-- (home_team, away_team) name pair.

{{
    config(
        materialized='incremental',
        unique_key='match_key',
        incremental_strategy='delete+insert'
    )
}}

with results as (

    select *
    from {{ ref('int_results_scored') }}

    {% if is_incremental() %}
    where source_loaded_at > (select max(source_loaded_at) from {{ this }})
    {% endif %}

),

matches as (

    select match_key, match_no
    from {{ ref('dim_match') }}

),

teams as (

    select team_key, team_name
    from {{ ref('dim_team') }}

)

select
    m.match_key,
    ht.team_key                                as home_team_key,
    awt.team_key                               as away_team_key,
    r.home_score,
    r.away_score,
    r.result,
    case
        when r.result = 'home_win' then ht.team_key
        when r.result = 'away_win' then awt.team_key
        else null
    end                                        as winner_team_key,
    r.kickoff_utc                              as played_at,
    r.source_loaded_at,
    current_timestamp                          as loaded_at
from results r
left join matches m
    on r.match_no = m.match_no
left join teams ht
    on r.home_team = ht.team_name
left join teams awt
    on r.away_team = awt.team_name
