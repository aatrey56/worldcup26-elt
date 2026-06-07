---
title: Group Standings
---

The 48 teams are drawn into 12 groups (A through L) of 4. The top two from each group, plus the eight best third placed teams, advance to the round of 32.

Standings update as group stage matches are played. Before kickoff these tables are empty, which is expected.

```sql standings
select
  s.group_letter,
  s.rank,
  t.team_name,
  t.fifa_code,
  s.played,
  s.won,
  s.drawn,
  s.lost,
  s.gf,
  s.ga,
  s.gd,
  s.points,
  s.qualified_flag
from warehouse.fct_group_standings s
inner join warehouse.dim_team t
  on s.team_key = t.team_key
order by s.group_letter, s.rank
```

```sql groups_list
select distinct group_letter
from warehouse.dim_team
where group_letter is not null
order by group_letter
```

{#if standings.length > 0}

{#each groups_list as g}

## Group {g.group_letter}

<DataTable data={standings.filter(d => d.group_letter === g.group_letter)}>
  <Column id=rank title="#" align=center />
  <Column id=team_name title="Team" />
  <Column id=played title="P" align=center />
  <Column id=won title="W" align=center />
  <Column id=drawn title="D" align=center />
  <Column id=lost title="L" align=center />
  <Column id=gf title="GF" align=center />
  <Column id=ga title="GA" align=center />
  <Column id=gd title="GD" align=center />
  <Column id=points title="Pts" align=center />
</DataTable>

{/each}

{:else}

No standings yet. The group stage begins on June 11, 2026. Standings will populate here once matches are played.

{/if}
