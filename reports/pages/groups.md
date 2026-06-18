---
title: Group Standings
---

The 48 teams are drawn into 12 groups (A through L) of 4. The top two from each group, plus the eight best third placed teams, advance to the round of 32.

These tables are **live**. While a group match is in play, the team shows a small colored dot next to the live score and its points update **as things stand** (a current win counts as +3, a draw +1, a loss +0), and the table re-ranks on those provisional points. Once the match ends, the result is locked in. The dot is green when the team is winning, grey when drawing, red when losing.

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
  s.is_playing,
  -- a small colored status dot + the live score, rendered as HTML (the Live
  -- column uses contentType=html). The dot colour shows the in-play result;
  -- scores are cast to int because Evidence stores them as float in the parquet
  -- (so a raw concat would read "2.0-1.0").
  case
    when not s.is_playing then ''
    else
      '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
      || 'margin-right:6px;vertical-align:middle;background:'
      || case s.live_status
        when 'winning' then '#16a34a'
        when 'losing' then '#ef4444'
        else '#9ca3af'
      end
      || ';"></span>'
      || cast(s.live_for as int) || '-' || cast(s.live_against as int)
  end as live
from warehouse.fct_group_standings_live s
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
  <Column id=live title="Live" contentType=html align=center />
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
