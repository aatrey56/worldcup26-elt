# CLAUDE.md - World Cup 2026 ELT

## What this repo is
End-to-end ELT for the 2026 World Cup: Airflow (Astro) orchestrates dbt (via Cosmos) into DuckDB,
served by an Evidence.dev dashboard. Live during the tournament (Jun 11 to Jul 19, 2026).

## Map
- dags/                Airflow DAG (Cosmos DbtTaskGroup): load_raw -> load_fifa -> dbt build -> publish (placeholder); Slack callback
- include/extract/      football-data.org + FIFA (api.fifa.com, free) clients + idempotent loaders. FIFA is PRIMARY for
                        live scores/standings/shots; football-data is the fallback (base_client.py shared; raw_tables.py
                        helpers; api_football.py is the 2022-2024 fallback)
- include/              third_place_seeding.py + annex_c_map.json (FIFA Annexe C R32 resolver, pure stdlib, has self_test);
                        schedule_window.py (live-window gate for the auto-update cron)
- include/data/raw/     cached raw JSON responses (gitignored); raw_sample/ committed for hermetic CI
- ml/                   offline xG model training (train_xg.py); outputs the dbt/seeds/xg_model.csv coefficients
                        (sklearn is dev-only; scoring is pure SQL in fct_shot)
- dbt/                  staging -> intermediate -> marts (star schema) + 130 tests + seeds. int_projected_r32 is a dbt
                        PYTHON model (wraps the include/ resolver); every other model is SQL
- reports/              Evidence dashboard (groups [live standings], bracket [live + projected R32], leaderboard,
                        scorers, xg, shots, teams; reads the warehouse)
- analysis/euro2024/    standalone StatsBomb xT/VAEP/carry analysis (own venv; not in the live pipeline)
- .github/workflows/    ci.yml (lint + hermetic dbt build/test) and deploy.yml (live load + build + Pages; 6h baseline cron +
                        external repository_dispatch ping gated to live match windows; GitHub cron is too flaky for 5-min.
                        See docs/LIVE_UPDATES.md)

## Stack
Astro/Airflow 3.x, dbt-core + astronomer-cosmos, dbt-duckdb (swap to Snowflake/MotherDuck via
profile only; pandas + pyarrow back the one dbt python model), Evidence.dev, ruff + sqlfluff.

## Rules
- Idempotent tasks. Re-running changes nothing unintended.
- dbt only via Cosmos, never a BashOperator.
- DuckDB is single-writer: threads=1 on the DuckDB profile, limit parallel dbt tasks.
- Secrets via .env and Airflow Variables/Connections only.
- Every mart documented and tested. No SELECT * in marts. ref()/source() only.
- fct_result is incremental (delete+insert) in the orchestrated path, keyed on the source-agnostic schedule match_no.
  FIFA is primary (is_live/source flags); football-data is the fallback. is_live rows show on the dashboard but are
  excluded from standings/aggregates/bracket-winner until full time. FIFA result-scoring is scoped to var(fifa_season_id).
- Live vs official standings: fct_group_standings_live folds in-play scores in "as things stand"; fct_group_standings
  is finished-only. fct_bracket projects the R32 live from the live standings, locking once the group stage is final.
- Third-place R32 seeding uses the committed include/ resolver via the int_projected_r32 dbt python model (the only
  python in the dbt DAG). Do NOT rebuild the 495-combination Annexe C table; it is reference data with a self_test
  and a dbt integrity test.
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
