-- One row per knockout match (32 rows, always present even pre-tournament:
-- the placeholder labels carry through and scores / winner are null until
-- played). No sentinel is needed because dim_match supplies all 32 knockout
-- rows regardless of whether any result has been recorded.
select
  match_no,
  match_key,
  match_id,
  stage,
  round_label,
  match_date,
  kickoff_et,
  channel_en,
  channel_es,
  venue,
  home_label,
  away_label,
  home_score,
  away_score,
  home_pens,
  away_pens,
  winner_label,
  home_seed,
  away_seed,
  home_clinched,
  away_clinched,
  is_projected,
  is_provisional
from main.fct_bracket
