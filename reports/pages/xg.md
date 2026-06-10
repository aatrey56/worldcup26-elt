---
title: Expected Goals (xG)
---

Expected goals (xG) estimates the probability that a shot becomes a goal, based on where it was taken from. The values here come from a **custom xG model** trained offline on FIFA shot coordinates: a logistic model over shot distance and angle, with penalties scored at their empirical conversion rate. The coefficients are baked into the warehouse and applied in pure SQL, so every shot is scored the same way at ingest and on this page. This is the project's machine-learning showcase, not an off-the-shelf number.

```sql player_xg
select
  player_name,
  position,
  shots,
  goals,
  total_xg,
  xg_per_shot,
  finishing
from warehouse.agg_player_xg
where player_id is not null
order by total_xg desc, goals desc
limit 25
```

```sql finishing
select
  player_name,
  position,
  goals,
  total_xg,
  finishing
from warehouse.agg_player_xg
where player_id is not null
order by finishing desc, goals desc
limit 25
```

{#if player_xg.length > 0}

## Top players by total xG

The volume and quality of chances each player has generated.

<DataTable data={player_xg} rows=all>
  <Column id=player_name title="Player" />
  <Column id=position title="Pos" align=center />
  <Column id=shots title="Shots" align=center />
  <Column id=goals title="Goals" align=center />
  <Column id=total_xg title="xG" align=center fmt='#,##0.00' />
  <Column id=xg_per_shot title="xG / shot" align=center fmt='#,##0.00' />
</DataTable>

## Finishing: goals versus xG

Finishing is goals minus total xG. A positive value means a player has scored more than their chances were worth (over-performance / clinical finishing); a negative value means under-performance.

<DataTable data={finishing} rows=all>
  <Column id=player_name title="Player" />
  <Column id=position title="Pos" align=center />
  <Column id=goals title="Goals" align=center />
  <Column id=total_xg title="xG" align=center fmt='#,##0.00' />
  <Column id=finishing title="Goals - xG" align=center fmt='+#,##0.00;-#,##0.00' />
</DataTable>

{:else}

No shots have been recorded yet, so there is nothing for the xG model to score. Once matches are played, the per-player xG and finishing tables will populate here.

{/if}

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
