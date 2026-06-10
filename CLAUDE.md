# CLAUDE.md - World Cup 2026 ELT

## What this repo is
End-to-end ELT for the 2026 World Cup: Airflow (Astro) orchestrates dbt (via Cosmos) into DuckDB,
served by an Evidence.dev dashboard. Live during the tournament (Jun 11 to Jul 19, 2026).

## Map
- dags/                Airflow DAG (Cosmos DbtTaskGroup): load_raw -> load_fifa -> dbt build -> publish; Slack callback
- include/extract/      football-data.org client + FIFA (api.fifa.com, free, shot x,y) client + idempotent loaders
                        (base_client.py shared; raw_tables.py helpers; api_football.py is the 2022-2024 fallback)
- include/data/raw/     cached raw JSON responses (gitignored); raw_sample/ committed for hermetic CI
- ml/                   offline xG model training (train_xg.py); outputs the dbt/seeds/xg_model.csv coefficients
                        (sklearn is dev-only; scoring is pure SQL in fct_shot)
- dbt/                  staging -> intermediate -> marts (star schema) + 120 tests + seeds
- reports/              Evidence dashboard (bracket, leaderboard, scorers, xg, shots, teams; reads the warehouse)
- analysis/euro2024/    standalone StatsBomb xT/VAEP/carry analysis (own venv; not in the live pipeline)
- .github/workflows/    ci.yml (lint + hermetic dbt build/test) and deploy.yml (live load + build + Pages cron every 6h)

## Stack
Astro/Airflow 3.x, dbt-core + astronomer-cosmos, dbt-duckdb (swap to Snowflake/MotherDuck via
profile only), Evidence.dev, ruff + sqlfluff.

## Rules
- Idempotent tasks. Re-running changes nothing unintended.
- dbt only via Cosmos, never a BashOperator.
- DuckDB is single-writer: threads=1 on the DuckDB profile, limit parallel dbt tasks.
- Secrets via .env and Airflow Variables/Connections only.
- Every mart documented and tested. No SELECT * in marts. ref()/source() only.
- fct_result is incremental in the orchestrated path.
- Staging is 1:1 with sources: rename, cast, clean, nothing more.
- Surrogate keys via dbt_utils.generate_surrogate_key. Document grain in each model.
- Knockout home_team/away_team in the seed are placeholders (Winner A, 3rd A/B/C/D/F, TBD).
  Staging must treat any non-country value as a placeholder when building dim_match.
- Pin tool/package versions only after web-verifying latest stable. Files with VERIFY_* markers
  must be resolved before that component is built.
- No em dashes in any output (code, comments, docs, commits, README). Conventional commits, small PRs.

## Definition of done (project)
Deployed Airflow running the DAG on a schedule, live Evidence dashboard, hosted dbt docs, CI green,
incremental load and idempotent backfill demonstrated, a data quality gate that fails the DAG on bad
data.

## Verify
make lint; make dbt; astro dev start; (in reports) npm run dev
