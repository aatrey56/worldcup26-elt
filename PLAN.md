# Build Plan + TODO - World Cup 2026 ELT

Working tracker for the phased build. Each phase is done only when its Definition of Done (DoD)
passes its verification command. Build mode for this project: full-auto (agent-built), with a
walkthrough after each phase so the code is interview-defensible.

## Prerequisites (one-time, before Phase 0 build) - NEEDS YOU

These are external/system steps no agent can do. Approve before the real build starts.

- [ ] Install Astro CLI (`brew install astro` or the official curl installer). VERIFY latest.
- [ ] Install dbt-duckdb + duckdb locally in a venv for fast local dbt runs (optional but useful).
- [ ] Sign up for API-Football (api-sports.io), get the free-tier API key.
- [ ] (Later) Astronomer trial account, Netlify/Vercel account, GitHub repo, Slack incoming webhook.

## Version pins to resolve (search "VERIFY" markers) - do FIRST in Phase 0 build

- [ ] Dockerfile: Astro Runtime tag (Airflow 3.x).
- [ ] requirements.txt: astronomer-cosmos, dbt-duckdb, duckdb, requests, tenacity.
- [ ] dbt/packages.yml: dbt_utils version.
- [ ] .pre-commit-config.yaml: ruff + sqlfluff hook revs.

---

## Phase 0 - Scaffold and local Airflow
- [x] Repo directory tree
- [x] Config boilerplate (Dockerfile, requirements, Makefile, ruff, sqlfluff, pre-commit, env)
- [x] CLAUDE.md, README, .gitignore
- [x] Seed placed at dbt/seeds/schedule_seed.csv (104 rows confirmed)
- [x] git init
- [ ] Resolve VERIFY version pins
- [ ] `astro dev init` reconcile (merge generated Astro files with this scaffold)
- [ ] DoD: `astro dev start` healthy + `make lint` clean

## Phase 1 - Ingestion (extract + load) - needs API key
- [ ] include/extract/api_football.py (auth, tenacity retry, rate-limit, JSON cache)
- [ ] Confirm WC league id + season + response shape from the live API (throwaway probe)
- [ ] include/extract/load_raw.py (idempotent upsert into DuckDB raw schema)
- [ ] DoD: raw.fixtures + raw.standings populated; re-run load_raw -> identical row counts

## Phase 2 - dbt models, tests, docs - FULLY testable on seed, no API
- [ ] staging: stg_matches, stg_teams, stg_venues, stg_standings (+ _sources.yml, _staging.yml)
- [ ] intermediate: int_results_scored, int_group_table (FIFA tiebreakers documented)
- [ ] marts: dim_team, dim_venue, dim_match, fct_result, fct_group_standings, agg_team_tournament
- [ ] tests: generic (unique/not_null/relationships/accepted_values) + dbt_utils + 3 singular
- [ ] DoD: `dbt build` passes full suite; dim_match = 104 (72 group); docs generate

## Phase 3 - Orchestration (Cosmos DAG) - needs Docker
- [ ] dags/world_cup_elt.py (extract -> load_raw -> Cosmos DbtTaskGroup -> publish)
- [ ] dags/callbacks.py (Slack on_failure_callback)
- [ ] @daily, catchup=False; single-writer DuckDB handling (threads=1, task concurrency)
- [ ] DoD: DAG green end to end; dbt models+tests are individual tasks; forced test failure alerts

## Phase 4 - Incremental load + backfill - FULLY testable locally
- [ ] fct_result -> incremental on match_key (merge), documented predicate
- [ ] Idempotent backfill proven; docs/backfill.md with exact commands
- [ ] DoD: incremental re-run updates only changed rows; backfill reproducible

## Phase 5 - Serving (Evidence) - FULLY testable locally
- [ ] reports/ Evidence project, DuckDB datasource
- [ ] pages: index.md, groups.md, [team].md, bracket.md (all query marts, no hardcoded data)
- [ ] DoD: `npm run dev` renders from warehouse; `npm run build` succeeds

## Phase 6 - Quality, CI/CD, docs, deploy - needs accounts
- [ ] .github/workflows/ci.yml (lint + dbt build + test, hermetic via committed raw sample)
- [ ] .github/workflows/docs.yml (dbt docs -> gh-pages)
- [ ] Deploy Evidence (Netlify/Vercel); optional astro deploy
- [ ] README: diagram, run steps, GIF, live links
- [ ] DoD: CI green on PR; docs hosted; dashboard live

## Phase 7 - Stretch (optional)
- [ ] Snowflake/MotherDuck swap target + screenshot
- [ ] dbt snapshot (SCD) on FIFA rankings/squads
- [ ] Soda as second QA layer; dbt source freshness
