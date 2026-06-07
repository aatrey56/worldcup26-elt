---
title: FIFA World Cup 2026
---

The 23rd FIFA World Cup runs from **June 11 to July 19, 2026**, hosted across the United States, Canada, and Mexico. This is the first edition with 48 teams, played over 104 matches in 16 host cities.

**How to watch (United States):** English language coverage on FOX and FS1. Spanish language coverage on Telemundo and Universo.

```sql tournament_counts
select
  (select count(*) from warehouse.dim_match) as total_matches,
  (select count(*) from warehouse.dim_team) as total_teams,
  (select count(*) from warehouse.dim_venue) as total_venues
```

<BigValue
  data={tournament_counts}
  value=total_matches
  title="Matches"
/>

<BigValue
  data={tournament_counts}
  value=total_teams
  title="Teams"
/>

<BigValue
  data={tournament_counts}
  value=total_venues
  title="Venues"
/>

## Most recent results

```sql recent_results
select
  m.match_no,
  m.match_date,
  m.round_label,
  ht.team_name as home_team,
  r.home_score,
  r.away_score,
  awt.team_name as away_team,
  r.result,
  r.played_at
from warehouse.fct_result r
inner join warehouse.dim_match m
  on r.match_key = m.match_key
inner join warehouse.dim_team ht
  on r.home_team_key = ht.team_key
inner join warehouse.dim_team awt
  on r.away_team_key = awt.team_key
order by coalesce(r.played_at, m.match_date) desc
limit 10
```

{#if recent_results.length > 0}

<DataTable data={recent_results} rows=10>
  <Column id=match_date title="Date" />
  <Column id=round_label title="Round" />
  <Column id=home_team title="Home" />
  <Column id=home_score title="" align=center />
  <Column id=away_score title="" align=center />
  <Column id=away_team title="Away" />
</DataTable>

{:else}

No matches have been played yet. The tournament kicks off on June 11, 2026. Check back here for live results.

{/if}
