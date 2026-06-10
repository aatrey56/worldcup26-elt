---
title: Teams
---

All 48 qualified teams. Select a team to see its fixtures, results, and group position.

```sql teams
select
  team_name,
  fifa_code,
  confederation,
  group_letter,
  '/teams/' || fifa_code as team_link
from warehouse.dim_team
order by group_letter, team_name
```

<DataTable data={teams} search=true rows=all>
  <Column id=group_letter title="Group" align=center />
  <Column id=team_link contentType=link linkLabel=team_name title="Team" openInNewTab=false />
  <Column id=fifa_code title="Code" align=center />
  <Column id=confederation title="Confederation" />
</DataTable>
