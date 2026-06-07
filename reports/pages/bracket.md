---
title: Knockout Bracket
---

The knockout phase runs from the round of 32 through to the final on July 19, 2026 at MetLife Stadium. With 48 teams, 2026 introduces a round of 32 for the first time.

The fixtures below are listed in match order across each knockout round. Team names are filled in once the group stage and preceding rounds are decided.

```sql knockout
select
  m.match_no,
  m.round_label,
  m.stage,
  m.match_date,
  v.venue_name,
  v.city,
  m.channel_en,
  m.channel_es
from warehouse.dim_match m
left join warehouse.dim_venue v
  on m.venue_key = v.venue_key
where m.stage in ('r32', 'r16', 'qf', 'sf', 'third', 'final')
order by m.match_no
```

```sql knockout_rounds
select distinct
  stage,
  round_label,
  min(match_no) as first_match
from warehouse.dim_match
where stage in ('r32', 'r16', 'qf', 'sf', 'third', 'final')
group by stage, round_label
order by first_match
```

{#if knockout.length > 0}

{#each knockout_rounds as r}

## {r.round_label}

<DataTable data={knockout.filter(d => d.stage === r.stage)}>
  <Column id=match_no title="Match" align=center />
  <Column id=match_date title="Date" />
  <Column id=venue_name title="Venue" />
  <Column id=city title="City" />
  <Column id=channel_en title="TV (EN)" />
  <Column id=channel_es title="TV (ES)" />
</DataTable>

{/each}

{:else}

The knockout fixtures are not loaded yet.

{/if}
