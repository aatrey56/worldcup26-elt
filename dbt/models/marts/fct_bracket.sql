-- Grain: one row per knockout match (dim_match where stage != 'group'), i.e.
-- the 32 knockout fixtures, for rendering the bracket tree.
--
-- TEAM LABEL RESOLUTION. A knockout slot is a placeholder until the feeding
-- match is played, so dim_match.home_team_key / away_team_key are NULL for these
-- rows (dim_match only resolves a team_key for non-placeholder rows). dim_match
-- itself does NOT expose the human placeholder text ("Winner Group A",
-- "Winner Match 73", ...): that text lives on stg_schedule.home_team /
-- away_team. So we join stg_schedule (by match_no) for the placeholder text, and
-- join fct_result (by match_key) for the REAL teams once the match is played:
-- fct_result.home_team_key / away_team_key carry the resolved teams, which we
-- map to country names via dim_team.
--   home_label = coalesce(resolved dim_team name via fct_result.home_team_key,
--                         stg_schedule placeholder text)
--   away_label = same on the away side.
-- winner_label resolves the same way from fct_result.winner_team_key, and is
-- null for an unplayed match. KNOWN LIMITATION: winner_team_key is derived only
-- from full-time score (int_results_scored), so a knockout decided on penalties
-- (level at full time) currently has a null winner_label. Penalty-shootout
-- winners need penalty-score ingestion (football-data score.penalties / FIFA
-- HomeTeamPenaltyScore) and must be wired before the knockout stage (Jun 28).
-- NOTE: home_label/away_label follow the played fixture's home/away once a match
-- is played (positional schedule reconciliation), which may differ from the
-- bracket feeder slot orientation; scores stay correctly paired with each label.
--
-- Empty-safe: pre-tournament fct_result is empty, so all 32 knockout rows are
-- present with their placeholder labels and null scores / null winner.

with knockout_matches as (

    select
        match_key,
        match_no,
        match_id,
        match_date,
        kickoff_et,
        stage,
        round_label,
        venue_key,
        channel_en,
        channel_es
    from {{ ref('dim_match') }}
    where stage != 'group'

),

schedule_labels as (

    -- placeholder team text (e.g. "Winner Group A") for each knockout slot
    select
        match_no,
        home_team as home_placeholder,
        away_team as away_placeholder
    from {{ ref('stg_schedule') }}

),

venues as (

    select
        venue_key,
        venue_name
    from {{ ref('dim_venue') }}

),

results as (

    -- FINISHED ONLY: the bracket resolves real teams, scores, and the winner
    -- from full-time results only. An in-play FIFA row (is_live = true) carries a
    -- partial score and a winner derived from that partial score, so including it
    -- would render a premature/incorrect winner that flips as the match swings or
    -- goes to penalties. Filtering is_live here keeps a live knockout slot on its
    -- placeholder labels (null score, null winner) until full time, consistent
    -- with how the group standings exclude in-play rows.
    select
        match_key,
        home_team_key,
        away_team_key,
        home_score,
        away_score,
        winner_team_key
    from {{ ref('fct_result') }}
    where not is_live

),

teams as (

    select
        team_key,
        team_name
    from {{ ref('dim_team') }}

),

projected as (

    -- PROJECTED R32 "as things stand": int_projected_r32 resolves the Round of 32
    -- matchups (match_no 73-88) from the CURRENT provisional group standings via
    -- the FIFA Annexe C third-place seeding. It only covers the R32 (the first
    -- knockout round); R16 onward stay on their placeholders until their feeder
    -- games are actually played. is_provisional is true until all 72 group
    -- matches are final, then the matchups lock.
    select
        match_no,
        home_team as projected_home,
        away_team as projected_away,
        is_provisional
    from {{ ref('int_projected_r32') }}

)

-- LABEL PRECEDENCE: actual played team (fct_result) > projected team (current
-- standings, R32 only) > schedule placeholder ("Winner A", "3rd A/B/C/D/F").
-- A slot shows a real projected team before its knockout game is played, and
-- switches to the actual team once that game has a finished result.
select
    km.match_no,
    km.match_key,
    km.match_id,
    km.stage,
    km.round_label,
    km.match_date,
    km.kickoff_et,
    km.channel_en,
    km.channel_es,
    v.venue_name as venue,
    coalesce(ht.team_name, p.projected_home, sl.home_placeholder) as home_label,
    coalesce(awt.team_name, p.projected_away, sl.away_placeholder) as away_label,
    r.home_score,
    r.away_score,
    wt.team_name as winner_label,
    -- the matchup is shown from projection (not an actual result) when no
    -- finished result exists yet but a projected team is available.
    (r.match_key is null and p.match_no is not null) as is_projected,
    -- the projection is provisional until the group stage is complete.
    (r.match_key is null and coalesce(p.is_provisional, false)) as is_provisional
from knockout_matches as km
left join schedule_labels as sl
    on km.match_no = sl.match_no
left join venues as v
    on km.venue_key = v.venue_key
left join results as r
    on km.match_key = r.match_key
left join teams as ht
    on r.home_team_key = ht.team_key
left join teams as awt
    on r.away_team_key = awt.team_key
left join teams as wt
    on r.winner_team_key = wt.team_key
left join projected as p
    on km.match_no = p.match_no
