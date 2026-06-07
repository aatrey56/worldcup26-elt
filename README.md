# World Cup 2026 ELT Pipeline

End-to-end ELT for the 2026 FIFA World Cup (Jun 11 to Jul 19, 2026). Airflow (Astro) orchestrates
dbt (via Cosmos) into DuckDB, transforms live fixtures, results, and standings into a tested star
schema, and serves an Evidence.dev dashboard that refreshes daily during the tournament.

> Status: scaffolded. Real build (models, DAG, ingestion, dashboard) pending. See `PLAN.md`.

## Architecture

```mermaid
flowchart LR
    api[API-Football<br/>live data] -->|extract, cached| raw[(raw JSON<br/>on disk)]
    seed[schedule_seed.csv<br/>104 matches] --> dbt
    raw -->|idempotent load| duck[(DuckDB<br/>raw schema)]
    duck --> dbt[dbt via Cosmos<br/>staging - intermediate - marts<br/>+ quality tests]
    dbt -->|tests pass| marts[(marts<br/>dim_* / fct_*)]
    marts --> dash[Evidence.dev<br/>live dashboard]
    airflow[Airflow / Astro<br/>daily schedule] -.orchestrates.-> raw
    airflow -.orchestrates.-> dbt
    dbt -.on failure.-> slack[Slack alert]
    dbt -.docs.-> pages[dbt lineage<br/>GitHub Pages]
```

## Data model (star schema)

- Dimensions: `dim_team`, `dim_venue`, `dim_match` (104 matches, seeded)
- Facts: `fct_result` (incremental), `fct_group_standings`
- Aggregate: `agg_team_tournament`

## Run locally

Prerequisites: Docker, the Astro CLI, Node 22+. See `PLAN.md` Phase 0 for setup.

```
make up        # start local Airflow
make dbt       # dbt seed + run + test
make evidence  # run the dashboard in dev mode
make lint      # ruff + sqlfluff
```

## Links

- Live dashboard: _TBD after deploy_
- dbt docs (lineage): _TBD after deploy_

## License

Personal portfolio project.
