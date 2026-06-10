-- Grain: one row per FINISHED match.
--
-- INCREMENTAL model. unique_key = match_key. Strategy = delete+insert, which
-- gives upsert (merge) semantics on DuckDB (DuckDB has no native MERGE): dbt
-- deletes the incoming match_keys from the target, then inserts the new rows,
-- so a corrected score replaces its existing row and never duplicates it.
--
-- Incremental predicate (FIX 6): on incremental runs we only pull source rows
-- whose source_loaded_at is newer than the newest one already loaded.
-- source_loaded_at is the PROVIDER'S lastUpdated timestamp (carried through
-- int_results_scored), NOT the loader's load timestamp. The loader restamps its
-- load timestamp on every full-snapshot run, so keying off it would reprocess
-- ALL rows every run; lastUpdated only advances when the provider actually
-- changes a match, so the predicate genuinely re-pulls only new finished
-- matches and corrected scores, skipping unchanged rows. On the first run the
-- table does not exist, so is_incremental() is false and every finished match
-- is loaded.
--
-- match_key is obtained by joining int_results_scored to dim_match on the
-- API fixture_id (int_results_scored.fixture_id = dim_match.match_id), the
-- stable id-based reconciliation that works for both group and knockout rows.
-- FIX 1: rows whose fixture_id does not reconcile to a dim_match (null
-- match_key) are dropped here. delete+insert cannot dedupe on a null key, so a
-- null-key row would accumulate; the unmapped_finished_results singular test
-- fails loudly if a real finished result is ever dropped this way.

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
    -- coalesce guards the empty-table case: before any match has finished the
    -- table exists but is empty, so max(...) is NULL and `x > NULL` would filter
    -- out the FIRST results to ever arrive. Fall back to a floor timestamp so
    -- the first finished matches load.
    where source_loaded_at > (
        select coalesce(max(source_loaded_at), timestamp '1900-01-01')
        from {{ this }}
    )
    {% endif %}

),

matches as (

    select match_key, match_id
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
    on r.fixture_id = m.match_id
left join teams ht
    on r.home_team = ht.team_name
left join teams awt
    on r.away_team = awt.team_name
where m.match_key is not null
