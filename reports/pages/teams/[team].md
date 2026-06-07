```sql team_info
select
  team_key,
  team_name,
  fifa_code,
  confederation,
  group_letter,
  is_host
from warehouse.dim_team
where fifa_code = '${params.team}'
```

# <Value data={team_info} column=team_name />

Group <Value data={team_info} column=group_letter />, <Value data={team_info} column=confederation />.

## Group position

```sql group_position
select
  s.rank,
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
where t.fifa_code = '${params.team}'
```

{#if group_position.length > 0}

<DataTable data={group_position}>
  <Column id=rank title="Rank" align=center />
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

No group standings yet. They will appear once the group stage begins.

{/if}

## Fixtures

```sql fixtures
select
  m.match_no,
  m.match_date,
  m.kickoff_et,
  m.round_label,
  m.group_letter,
  case when ht.fifa_code = '${params.team}' then 'Home' else 'Away' end as venue_side,
  ht.team_name as home_team,
  at.team_name as away_team,
  m.channel_en,
  m.channel_es
from warehouse.dim_match m
inner join warehouse.dim_team ht
  on m.home_team_key = ht.team_key
inner join warehouse.dim_team at
  on m.away_team_key = at.team_key
where ht.fifa_code = '${params.team}'
   or at.fifa_code = '${params.team}'
order by m.match_no
```

{#if fixtures.length > 0}

<DataTable data={fixtures}>
  <Column id=match_date title="Date" />
  <Column id=round_label title="Round" />
  <Column id=home_team title="Home" />
  <Column id=away_team title="Away" />
  <Column id=channel_en title="TV (EN)" />
  <Column id=channel_es title="TV (ES)" />
</DataTable>

{:else}

No fixtures found for this team.

{/if}

## Results

```sql team_results
select
  m.match_no,
  m.match_date,
  m.round_label,
  ht.team_name as home_team,
  r.home_score,
  r.away_score,
  at.team_name as away_team,
  r.result
from warehouse.fct_result r
inner join warehouse.dim_match m
  on r.match_key = m.match_key
inner join warehouse.dim_team ht
  on r.home_team_key = ht.team_key
inner join warehouse.dim_team at
  on r.away_team_key = at.team_key
where ht.fifa_code = '${params.team}'
   or at.fifa_code = '${params.team}'
order by m.match_no
```

{#if team_results.length > 0}

<DataTable data={team_results}>
  <Column id=match_date title="Date" />
  <Column id=round_label title="Round" />
  <Column id=home_team title="Home" />
  <Column id=home_score title="" align=center />
  <Column id=away_score title="" align=center />
  <Column id=away_team title="Away" />
</DataTable>

{:else}

This team has not played any matches yet.

{/if}
