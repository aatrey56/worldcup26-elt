-- One row per real team (all 48, never empty: driven by a left join from
-- dim_team in the mart). No sentinel needed.
select
  team_key,
  team_name,
  fifa_code,
  group_letter,
  matches_played,
  wins,
  draws,
  losses,
  gf,
  ga,
  gd,
  points,
  group_rank,
  qualified_flag,
  stage_reached,
  overall_rank
from main.agg_team_leaderboard
