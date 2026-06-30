-- Grain: one row per scheduled match (match_no) that has a usable score,
-- preferring FIFA (live, first-party) and falling back to football-data.org.
--
-- WHY FIFA IS PRIMARY: the football-data.org free tier is badly delayed; during
-- a live match it reports status=TIMED with null scores, so a results model
-- built only on it is EMPTY mid-game and the standings/dashboard go dark. The
-- FIFA api.fifa.com feed is first-party and updates in-play, so we take it as
-- the source of truth and keep football-data as a fallback (it still backfills
-- any match FIFA has not surfaced, and it is the only source on the hermetic
-- sample, which carries no FIFA match results).
--
-- A match counts as scored when both scores are non-null AND:
--   FIFA: status in (0, 3, 12) -> finished/played (0) or in-play/live (3, 12).
--   football-data: status = 'FINISHED' (a FINISHED match with null scores is an
--     award/abandonment and is excluded rather than mislabelled as 0-0).
--
-- is_live = true ONLY for FIFA in-play statuses (3, 12). Finished matches
-- (FIFA 0, all football-data) are is_live = false. Downstream, the group table
-- and per-team aggregates count only is_live = false rows, so an in-progress
-- score shows on the dashboard but does NOT move the standings until full time.
--
-- COALESCE PER match_no: if FIFA has a row for a match_no we use it; otherwise
-- we use football-data's. Output is one row per match_no. fixture_id is the
-- football-data id (null for FIFA-only rows); fifa_match_id is the FIFA id
-- (null for football-data rows); both are passed through for traceability.
--
-- Materialized as a table: it is recomputed by several downstream models
-- (fct_result, int_group_table), so we compute it once.

{{ config(materialized='table') }}

with schedule as (

    select
        match_no,
        group_letter
    from {{ ref('stg_schedule') }}

),

-- ========================= FIFA (primary) =========================
fifa_crosswalk as (

    select
        fifa_name,
        seed_name
    from {{ ref('fifa_team_name_crosswalk') }}

),

fifa_map as (

    select
        fifa_match_id,
        match_no
    from {{ ref('int_fifa_match_map') }}

),

fifa_raw as (

    select
        match_id as fifa_match_id,
        status,
        match_date,
        home_team_id,
        away_team_id,
        home_team_name,
        away_team_name,
        home_score,
        away_score,
        home_penalty_score,
        away_penalty_score,
        winner_team_id,
        loaded_at
    from {{ ref('stg_fifa_matches') }}
    where
        status in (0, 3, 12)
        and home_score is not null
        and away_score is not null
        -- current season only; the sample's 2022 FIFA fixtures are not results.
        and season_id = {{ var('fifa_season_id') }}

),

fifa_scored as (

    select
        fm.match_no,
        f.fifa_match_id,
        cast(null as bigint) as fixture_id,
        sch.group_letter,
        coalesce(hx.seed_name, f.home_team_name) as home_team,
        coalesce(ax.seed_name, f.away_team_name) as away_team,
        f.home_score,
        f.away_score,
        case
            when f.home_score > f.away_score then 'home_win'
            when f.home_score < f.away_score then 'away_win'
            else 'draw'
        end as result,
        case
            when f.home_score > f.away_score then 3
            when f.home_score = f.away_score then 1
            else 0
        end as home_points,
        case
            when f.away_score > f.home_score then 3
            when f.away_score = f.home_score then 1
            else 0
        end as away_points,
        (f.status in (3, 12)) as is_live,
        cast('fifa' as varchar) as source,
        f.match_date as kickoff_ts,
        -- penalty-shootout scores (null unless the match went to a shootout).
        f.home_penalty_score as home_pens,
        f.away_penalty_score as away_pens,
        -- the DECIDED winner's canonical seed name, resolved from FIFA's Winner
        -- team id. Set for any decided knockout incl. shootouts/extra time, so a
        -- level full-time score (a shootout) still carries its true winner. Null
        -- for draws and unplayed matches. The Winner id equals one of the two team
        -- ids, so we map it back to the (crosswalked) seed name.
        case
            when f.winner_team_id = f.home_team_id
                then coalesce(hx.seed_name, f.home_team_name)
            when f.winner_team_id = f.away_team_id
                then coalesce(ax.seed_name, f.away_team_name)
        end as winner_team_name,
        -- source_loaded_at drives the fct_result incremental predicate. For FIFA
        -- we use the LOADER timestamp (loaded_at), which strictly advances on
        -- every run, NOT LastPeriodUpdate. LastPeriodUpdate is null in-play and
        -- then freezes at the end-of-play time once the match finishes; that
        -- frozen value can be EARLIER than the last in-play run's loaded_at, so a
        -- `source_loaded_at > max` predicate would skip the finishing row and
        -- leave a stale live score with is_live still true. loaded_at advancing
        -- every run guarantees the live row re-pulls while in play AND the final
        -- score lands when it finishes. Cost: finished FIFA rows re-pull every
        -- run, but the model is at most 104 rows so that is negligible.
        f.loaded_at as source_loaded_at
    from fifa_raw as f
    join fifa_map as fm
        on f.fifa_match_id = fm.fifa_match_id
    left join schedule as sch
        on fm.match_no = sch.match_no
    left join fifa_crosswalk as hx
        on f.home_team_name = hx.fifa_name
    left join fifa_crosswalk as ax
        on f.away_team_name = ax.fifa_name

),

-- ===================== football-data (fallback) =====================
fd_map as (

    select
        fixture_id,
        match_no
    from {{ ref('int_match_map') }}

),

fd_raw as (

    select
        fixture_id,
        kickoff_utc,
        last_updated,
        loaded_at,
        home_team,
        away_team,
        home_score,
        away_score
    from {{ ref('stg_matches') }}
    where
        status = 'FINISHED'
        and home_score is not null
        and away_score is not null

),

fd_scored as (

    select
        mm.match_no,
        cast(null as bigint) as fifa_match_id,
        f.fixture_id,
        sch.group_letter,
        f.home_team,
        f.away_team,
        f.home_score,
        f.away_score,
        case
            when f.home_score > f.away_score then 'home_win'
            when f.home_score < f.away_score then 'away_win'
            else 'draw'
        end as result,
        case
            when f.home_score > f.away_score then 3
            when f.home_score = f.away_score then 1
            else 0
        end as home_points,
        case
            when f.away_score > f.home_score then 3
            when f.away_score = f.home_score then 1
            else 0
        end as away_points,
        cast(false as boolean) as is_live,
        cast('football-data' as varchar) as source,
        f.kickoff_utc as kickoff_ts,
        -- football-data is the fallback and is not used for live knockouts, so it
        -- does not carry shootout scores or an explicit winner here; FIFA (primary)
        -- supplies those. A football-data-sourced knockout shootout would fall back
        -- to the score-based winner (null on a level score) - an accepted edge case.
        cast(null as int) as home_pens,
        cast(null as int) as away_pens,
        cast(null as varchar) as winner_team_name,
        -- source_loaded_at is the provider's lastUpdated (carried to drive the
        -- fct_result incremental predicate), coalesced to loaded_at so a null
        -- never drops the row. football-data rows are always finished, so
        -- lastUpdated stops advancing once final and the predicate correctly
        -- stops re-pulling them. See fct_result for the full rationale.
        coalesce(f.last_updated, f.loaded_at) as source_loaded_at
    from fd_raw as f
    left join fd_map as mm
        on f.fixture_id = mm.fixture_id
    left join schedule as sch
        on mm.match_no = sch.match_no

),

-- ===================== coalesce FIFA over football-data =====================
combined as (

    select
        match_no,
        fifa_match_id,
        fixture_id,
        group_letter,
        home_team,
        away_team,
        home_score,
        away_score,
        result,
        home_points,
        away_points,
        is_live,
        source,
        kickoff_ts,
        home_pens,
        away_pens,
        winner_team_name,
        source_loaded_at
    from fifa_scored
    where match_no is not null

    union all

    select
        match_no,
        fifa_match_id,
        fixture_id,
        group_letter,
        home_team,
        away_team,
        home_score,
        away_score,
        result,
        home_points,
        away_points,
        is_live,
        source,
        kickoff_ts,
        home_pens,
        away_pens,
        winner_team_name,
        source_loaded_at
    from fd_scored
    where match_no is not null

),

ranked as (

    -- one row per match_no: FIFA (source = 'fifa') ranks ahead of football-data.
    -- The source_loaded_at DESC secondary term makes the choice deterministic if
    -- a single source ever yields two rows for one match_no (the freshest wins),
    -- so src_rank = 1 is never an arbitrary pick.
    select
        *,
        row_number() over (
            partition by match_no
            order by
                case when source = 'fifa' then 0 else 1 end,
                source_loaded_at desc
        ) as src_rank
    from combined

)

select
    match_no,
    fifa_match_id,
    fixture_id,
    group_letter,
    home_team,
    away_team,
    home_score,
    away_score,
    result,
    home_points,
    away_points,
    is_live,
    source,
    kickoff_ts,
    home_pens,
    away_pens,
    winner_team_name,
    source_loaded_at
from ranked
where src_rank = 1
