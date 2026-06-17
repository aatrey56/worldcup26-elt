---
title: Knockout Bracket
---

The knockout phase runs from the round of 32 through to the final on July 19, 2026 at MetLife Stadium. With 48 teams, 2026 introduces a round of 32 for the first time.

This bracket is **live and projected**. The Round of 32 is filled in right now from the current group standings *as things stand* (using FIFA's official third-place seeding rules), so you can see who would play whom if the groups ended this minute. Those matchups are marked **projected** and shift as scores change; once all group games are final they **lock**, and once a knockout game is played the real result and the advancing team replace the projection. The Round of 16 onward stays on placeholders until its feeder games are decided.

```sql bracket
select
  match_no,
  stage,
  round_label,
  match_date,
  kickoff_et,
  channel_en,
  channel_es,
  venue,
  home_label,
  away_label,
  home_score,
  away_score,
  winner_label,
  -- cast scores to int: Evidence stores the nullable score columns as float in
  -- the parquet, so concatenating them directly would render "2.0 - 1.0".
  case
    when winner_label is not null and winner_label = home_label then home_label || '  (' || cast(home_score as int) || ' - ' || cast(away_score as int) || ')'
    when winner_label is not null and winner_label = away_label then away_label || '  (' || cast(home_score as int) || ' - ' || cast(away_score as int) || ')'
    when home_score is not null then home_label || '  ' || cast(home_score as int) || ' - ' || cast(away_score as int) || '  ' || away_label
    else home_label || '  vs  ' || away_label
  end as fixture,
  case when winner_label is not null then '-> ' || winner_label else '' end as advancing,
  case
    when winner_label is not null then ''
    when is_provisional then 'projected (as things stand)'
    when is_projected then 'confirmed matchup'
    else ''
  end as status
from warehouse.fct_bracket
order by match_no
```

```sql bracket_stages
select distinct
  stage,
  round_label,
  min(match_no) as first_match
from warehouse.fct_bracket
group by stage, round_label
order by first_match
```

{#if bracket.length > 0}

{#each bracket_stages as r}

## {r.round_label}

<DataTable data={bracket.filter(d => d.stage === r.stage)} rows=all>
  <Column id=match_no title="Match" align=center />
  <Column id=fixture title="Fixture" />
  <Column id=status title="Status" />
  <Column id=advancing title="Advances" />
  <Column id=match_date title="Date" />
  <Column id=venue title="Venue" />
  <Column id=channel_en title="TV (EN)" />
  <Column id=channel_es title="TV (ES)" />
</DataTable>

{/each}

{:else}

The knockout fixtures are not loaded yet. They will appear here as the bracket structure is built.

{/if}

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
