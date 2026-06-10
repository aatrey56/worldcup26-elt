---
title: Team Leaderboard
---

The best-performing teams across the tournament, ranked by points, then goal difference, then goals scored. All 48 teams appear from day one; their records fill in as matches are played.

```sql leaderboard
select
  overall_rank,
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
  case when qualified_flag then 'Yes' else '' end as qualified,
  stage_reached
from warehouse.agg_team_leaderboard
order by overall_rank
```

<DataTable data={leaderboard} search=true rows=all>
  <Column id=overall_rank title="#" align=center />
  <Column id=team_name title="Team" />
  <Column id=group_letter title="Grp" align=center />
  <Column id=matches_played title="P" align=center />
  <Column id=wins title="W" align=center />
  <Column id=draws title="D" align=center />
  <Column id=losses title="L" align=center />
  <Column id=gf title="GF" align=center />
  <Column id=ga title="GA" align=center />
  <Column id=gd title="GD" align=center />
  <Column id=points title="Pts" align=center />
  <Column id=qualified title="Qual" align=center />
</DataTable>

Before kickoff every team is level on zero points and ordered alphabetically, which is expected. Rankings reshuffle as results come in.

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
