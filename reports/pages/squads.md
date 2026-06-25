---
title: Squad Quality
---

How many of each team's players play their club football in a **top-5 European league** (the English Premier League, Spanish La Liga, Italian Serie A, German Bundesliga, and French Ligue 1). It is a rough proxy for the depth of elite club pedigree in a squad, and a useful piece of context rather than a prediction: Spain arrive stacked with top-5 players, yet still drew 0-0 with Cape Verde. Quality on paper is not the same as a result on the day.

```sql squad_quality
select
  team_name,
  group_letter,
  squad_size,
  top5_count,
  top5_pct
from warehouse.fct_squad_quality
where team_key is not null
order by top5_count desc, top5_pct desc, team_name asc
```

```sql top_ten
select
  team_name,
  top5_count
from warehouse.fct_squad_quality
where team_key is not null
order by top5_count desc, team_name asc
limit 10
```

{#if squad_quality.length > 0}

## Most top-5-league players

The ten squads with the most players based at a top-5 European club.

<BarChart
  data={top_ten}
  x=team_name
  y=top5_count
  swapXY=true
  sort=false
  yAxisTitle="Players in a top-5 league"
  colorPalette={['#2563eb']}
/>

## All teams

<DataTable data={squad_quality} search=true rows=all>
  <Column id=team_name title="Team" />
  <Column id=group_letter title="Grp" align=center />
  <Column id=squad_size title="Squad" align=center />
  <Column id=top5_count title="Top-5 league" align=center />
  <Column id=top5_pct title="%" align=center fmt='#,##0.0"%"' />
</DataTable>

Top-5 league means a player's club competes in the 2025/26 Premier League, La Liga, Serie A, Bundesliga, or Ligue 1. Squad lists are the announced 26-player squads.

{:else}

Squad lists are not available yet. Once the squads are published they will appear here with each team's count of top-5-league players.

{/if}

---

_Data: squads from Wikipedia (2026 FIFA World Cup squads); club leagues mapped to the 2025/26 top-5 European rosters. A context stat, not affiliated with FIFA._
