---
title: Shot Map
---

Every shot taken in the tournament, plotted by location on the attacking half. The x axis runs from the halfway line (0) to the goal being attacked (1); the y axis is the width of the pitch (0 to 1). Each point is colored by outcome (goal or no goal), and its expected-goals value comes from the project's custom xG model.

```sql shots
select
  x,
  y,
  xg,
  shot_distance,
  shot_angle,
  case when is_goal then 'Goal' else 'No goal' end as outcome,
  case when is_penalty then 'Penalty' else 'Open play' end as shot_type
from warehouse.fct_shot
where x is not null and y is not null
```

```sql shot_summary
select
  count(*) as shots,
  sum(case when outcome = 'Goal' then 1 else 0 end) as goals,
  avg(xg) as avg_xg
from ${shots}
```

{#if shots.length > 0}

<BigValue data={shot_summary} value=shots title="Shots" />
<BigValue data={shot_summary} value=goals title="Goals" />
<BigValue data={shot_summary} value=avg_xg title="Average xG" fmt='#,##0.00' />

<ScatterPlot
  data={shots}
  x=x
  y=y
  series=outcome
  xMin=0
  xMax=1
  yMin=0
  yMax=1
  xAxisTitle="Toward goal (0 = halfway, 1 = goal)"
  yAxisTitle="Pitch width"
  pointSize=12
  tooltipTitle=outcome
/>

Hover any point to see its xG, shot distance, and angle. The closer a shot is to the attacking goal (x near 1) and the more central it is (y near 0.5), the higher its modeled xG.

{:else}

No shots have been recorded yet. The shot map will populate here once matches are played; before kickoff there is no shot data to plot.

{/if}

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
