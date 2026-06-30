-- Grain: one row per match that has a usable score (FINISHED or, from FIFA,
-- IN-PLAY). The is_live flag distinguishes the two: is_live = true means the
-- score is from a match still in progress (FIFA primary), is_live = false means
-- the match is final. Live rows let the dashboard show in-progress scores;
-- downstream standings/aggregates filter to is_live = false so an in-play game
-- never moves the table until full time.
--
-- INCREMENTAL model. unique_key = match_key. Strategy = delete+insert, which
-- gives upsert (merge) semantics on DuckDB (DuckDB has no native MERGE): dbt
-- deletes the incoming match_keys from the target, then inserts the new rows,
-- so a corrected score (or a live score advancing to its final value) replaces
-- its existing row and never duplicates it.
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
-- seed match_no (int_results_scored.match_no = dim_match.match_no). match_no is
-- the source-agnostic reconciliation key, so it lands both FIFA-sourced and
-- football-data-sourced rows uniformly. team_keys come from dim_team by the
-- canonical seed team name.
-- FIX 1: rows whose match_no does not reconcile to a dim_match (null match_key)
-- are dropped here. delete+insert cannot dedupe on a null key, so a null-key row
-- would accumulate; the unmapped_finished_results singular test fails loudly if
-- a real result is ever dropped this way.
--
-- LIVE NOTE: a FIFA row's source_loaded_at is the loader timestamp (loaded_at),
-- which advances every run. That is intentional: the incremental predicate then
-- re-pulls the live match every run so its score updates, and delete+insert
-- upserts the same match_key in place. When the match finishes, loaded_at is
-- still advancing, so the final score lands the same way (see int_results_scored
-- for why loaded_at, not LastPeriodUpdate, is used for FIFA).

-- SCHEMA EVOLUTION: on_schema_change = 'append_new_columns' lets a persistent
-- incremental warehouse (the orchestrated Airflow path) absorb additive columns
-- without a full-refresh. NOTE: this change added the NOT NULL columns is_live
-- and source, so on a warehouse that already holds a pre-change fct_result the
-- new columns backfill as NULL on historical rows and the not_null tests flag
-- them. That migration therefore needs a one-time `dbt build --full-refresh
-- --select fct_result`. The live site is unaffected: the GitHub Pages deploy
-- rebuilds the warehouse from scratch every run, so fct_result is created fresh
-- with the full schema (is_incremental() is false on a fresh build).
{{
    config(
        materialized='incremental',
        unique_key='match_key',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
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

    select
        match_key,
        match_no,
        match_date
    from {{ ref('dim_match') }}

),

teams as (

    select
        team_key,
        team_name
    from {{ ref('dim_team') }}

)

select
    m.match_key,
    ht.team_key as home_team_key,
    awt.team_key as away_team_key,
    r.home_score,
    r.away_score,
    -- penalty-shootout scores (null unless a knockout went to a shootout), for the
    -- bracket's "1-1 (4-3 pens)" display.
    r.home_pens,
    r.away_pens,
    r.result,
    r.is_live,
    r.source,
    -- played_at is the actual kickoff timestamp carried from the winning source
    -- (FIFA Date / football-data kickoff_utc), NOT dim_match.match_date (which is
    -- date-only). A real timestamp keeps "most recent results" ordering stable
    -- among matches played on the same calendar day. Fall back to match_date if a
    -- source ever omits the kickoff.
    coalesce(r.kickoff_ts, m.match_date) as played_at,
    r.source_loaded_at,
    -- winner: the explicit FIFA winner (resolved from the Winner team id, so it
    -- covers shootout- and extra-time-decided knockouts where the full-time score
    -- is level) takes precedence; otherwise fall back to the full-time score. A
    -- shootout therefore keeps result = 'draw' (so tournament stats count it as a
    -- draw) while winner_team_key still advances the side that won the shootout.
    coalesce(
        wnr.team_key,
        case
            when r.result = 'home_win' then ht.team_key
            when r.result = 'away_win' then awt.team_key
        end
    ) as winner_team_key,
    current_timestamp as loaded_at
from results as r
left join matches as m
    on r.match_no = m.match_no
left join teams as ht
    on r.home_team = ht.team_name
left join teams as awt
    on r.away_team = awt.team_name
left join teams as wnr
    on r.winner_team_name = wnr.team_name
where m.match_key is not null
