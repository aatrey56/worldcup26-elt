---
title: Golden Boot
---

The race for the Golden Boot, awarded to the tournament's top scorer. Ranked by goals, then assists.

```sql scorers
select
  rank,
  player_name,
  team_name,
  goals,
  assists
from warehouse.agg_top_scorers
where rank is not null
order by goals desc, assists desc, player_name asc
```

{#if scorers.length > 0}

<DataTable data={scorers} rows=all>
  <Column id=rank title="#" align=center />
  <Column id=player_name title="Player" />
  <Column id=team_name title="Team" />
  <Column id=goals title="Goals" align=center />
  <Column id=assists title="Assists" align=center />
</DataTable>

{:else}

No goals have been scored yet. The Golden Boot race begins on June 11, 2026, and the leaderboard will fill in here once matches are played.

{/if}

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
