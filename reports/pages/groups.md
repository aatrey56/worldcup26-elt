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

```sql third_place_race
-- The 12 third-placed teams ranked across ALL groups; the best 8 advance to the
-- round of 32. FIFA's third-place tiebreaker (head-to-head does NOT apply across
-- groups) is, in order: points, overall goal difference, overall goals scored,
-- conduct score (cards, not ingested -> skipped), then the seeded FIFA World
-- Ranking, with team_name as the stable final fallback (matches
-- include/third_place_seeding.py). race_rank 1-8 advance; the page splits the
-- table after rank 8 to mark the qualification cut.
with thirds as (
  select
    s.group_letter,
    t.team_name,
    s.played, s.won, s.drawn, s.lost, s.gf, s.ga, s.gd, s.points,
    s.fifa_rank
  from warehouse.fct_group_standings_live s
  inner join warehouse.dim_team t
    on s.team_key = t.team_key
  where s.rank = 3
),
ranked as (
  select
    *,
    -- FIFA third-place order: points, overall GD, overall GF, then conduct
    -- (cards, not ingested -> skipped), then the seeded FIFA World Ranking,
    -- with team_name as the stable final fallback.
    row_number() over (
      order by points desc, gd desc, gf desc, fifa_rank asc nulls last, team_name asc
    ) as race_rank
  from thirds
)
select
  race_rank,
  group_letter,
  team_name,
  played, won, drawn, lost, gf, ga, gd, points
from ranked
order by race_rank
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

## Third-Place Race

The top two of every group qualify automatically; the **eight best third-placed teams** fill the rest of the round of 32. All 12 third-placed teams are ranked together across the groups. Head-to-head does **not** apply here. FIFA's order is: (1) points, (2) overall goal difference, (3) overall goals scored, (4) fair-play / conduct score, (5) FIFA World Ranking. Conduct (cards) is not ingested so it is skipped; the seeded FIFA World Ranking breaks any remaining tie.

The eight teams **above the break** advance; the four below are out as things stand. It re-ranks live as scores change.

<DataTable data={third_place_race.filter(d => d.race_rank <= 8)} rows=all>
  <Column id=race_rank title="#" align=center />
  <Column id=group_letter title="Grp" align=center />
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

<div style="height:2px;background:#9ca3af;border-radius:2px;margin:0.3rem 0;"></div>

<DataTable data={third_place_race.filter(d => d.race_rank > 8)} rows=all>
  <Column id=race_rank title="#" align=center />
  <Column id=group_letter title="Grp" align=center />
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

{:else}

No standings yet. The group stage begins on June 11, 2026. Standings will populate here once matches are played.

{/if}
