# World Cup 2026 ELT Pipeline

[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-aatrey56.github.io%2Fworldcup26--elt-2ea44f?style=for-the-badge&logo=github)](https://aatrey56.github.io/worldcup26-elt/)
[![dbt docs](https://img.shields.io/badge/dbt%20lineage%20docs-View-orange?style=for-the-badge&logo=dbt)](https://aatrey56.github.io/worldcup26-elt/dbt-docs/)

> **Live site:** https://aatrey56.github.io/worldcup26-elt/

An end-to-end, **live** data platform for the 2026 FIFA World Cup (Jun 11 to Jul 19, 2026).
Airflow (Astro) orchestrates dbt (via Cosmos) into DuckDB; a custom **expected-goals (xG) model**
is trained on FIFA shot coordinates and deployed as pure SQL; and an Evidence.dev dashboard
**updates near-live during matches** (a schedule-aware cron, ~5-10 min behind play) and every 6
hours otherwise. Live scores, group standings, and the knockout bracket come **first-party from
FIFA's public API**, with football-data.org as a fallback. Everything runs on **free data sources**
and **$0 of hosting**.

## Live

- **Dashboard:** https://aatrey56.github.io/worldcup26-elt/
  (overview, live [group standings](https://aatrey56.github.io/worldcup26-elt/groups/)
  with as-things-stand points and a winning/drawing/losing dot,
  live + projected [bracket](https://aatrey56.github.io/worldcup26-elt/bracket/),
  [team leaderboard](https://aatrey56.github.io/worldcup26-elt/leaderboard/),
  [top scorers](https://aatrey56.github.io/worldcup26-elt/scorers/),
  custom-[xG leaderboard](https://aatrey56.github.io/worldcup26-elt/xg/),
  [shot maps](https://aatrey56.github.io/worldcup26-elt/shots/),
  and per-team pages)
- **dbt lineage docs:** https://aatrey56.github.io/worldcup26-elt/dbt-docs/

## Architecture

```mermaid
flowchart LR
    fifa[FIFA api.fifa.com<br/>live scores / shot x,y /<br/>events / lineups] -->|idempotent load, primary| duck[(DuckDB)]
    fd[football-data.org<br/>results / standings, fallback] -->|idempotent load| duck
    seed[schedule_seed.csv<br/>104 matches] --> dbt
    xgseed[xg_model seed<br/>trained coefficients] --> dbt
    annex[Annexe C seeds<br/>third-place seeding] --> dbt
    duck --> dbt[dbt via Cosmos<br/>staging - intermediate - marts<br/>+ 130 quality tests]
    dbt -->|tests pass| marts[(marts: dim_*/fct_*<br/>fct_result.is_live, fct_shot.xg,<br/>fct_group_standings_live,<br/>projected fct_bracket, leaderboards)]
    marts --> dash[Evidence.dev dashboard]
    airflow[Airflow / Astro<br/>Cosmos DbtTaskGroup] -.orchestrates.-> duck
    gha[GitHub Actions<br/>6h baseline + 5-min<br/>gated live cron] -.runs.-> duck
    gha -.deploys.-> pages[GitHub Pages:<br/>dashboard + dbt docs]
    dbt -.on failure.-> slack[Slack alert]
    sb[StatsBomb open data<br/>Euro 2024 events] --> analysis[analysis/euro2024:<br/>xT / VAEP / carry]
```

## The data story (why it is built this way)

Live, event-level football data is one of the most locked-down datasets there is. There is **no
free source of full event data (passes/carries) for WC 2026**, so the project layers what is
genuinely obtainable:

- **FIFA's own public API** (`api.fifa.com`, free, first-party) is the live source of truth:
  **scores and group standings that update in-play**, the one free source of **shot coordinates**
  for 2026, plus events, lineups, and top scorers. The free football-data.org tier is delayed (it
  reports a live match as not-started), which is why FIFA is primary.
- **football-data.org** (free) is the **fallback** for results and standings, and the only results
  source on the hermetic CI sample.
- **A custom xG model** is trained offline on FIFA's own 2022 World Cup shots (logistic on shot
  distance + angle; penalties at the empirical conversion rate) and deployed as a **pure-SQL
  scorer** (coefficients live in a dbt seed), so the live pipeline needs no ML runtime. Calibration:
  predicted xG 170.02 vs 170 actual goals, Brier 0.116, ROC-AUC 0.74. Training the model on shot
  coordinates (rather than consuming a vendor's xG) is the modeling showcase.
- **StatsBomb open data** (free, historical) powers a separate, rigorous **player-valuation
  analysis** of Euro 2024 (`analysis/euro2024/`) using xT, out-of-fold VAEP, xGChain, opponent
  adjustment, minutes-weighted empirical-Bayes shrinkage, a separate goalkeeper model, and a "carry"
  score, since the full possession-value methods that 2026 free data cannot support are achievable
  on a completed tournament.

## Data model (DuckDB star schema, dbt)

- **Dimensions:** `dim_team`, `dim_venue`, `dim_match` (104, seeded), `dim_fifa_team`,
  `dim_fifa_player`.
- **Facts:** `fct_result` (incremental, keyed on the source-agnostic schedule `match_no`;
  FIFA-primary with `is_live`/`source` flags, football-data fallback), `fct_group_standings`
  (official, finished-only) and `fct_group_standings_live` (provisional "as things stand": in-play
  scores folded in, with a per-team winning/drawing/losing status), `fct_shot` (per shot, with
  SQL-scored `xg`), `fct_bracket` (knockout tree; its Round of 32 is **projected live** from current
  standings via FIFA's Annexe C third-place seeding (`int_projected_r32`), locks when the group
  stage ends, and resolves to actual results as games are played).
- **Aggregates:** `agg_team_tournament`, `agg_team_leaderboard`, `agg_player_xg` (xG, goals,
  finishing over/under), `agg_team_xg`, `agg_top_scorers`.
- **Quality gate:** 130 dbt tests (generic + dbt_utils + singular), including 1:1 FIFA- and
  football-data-to-schedule reconciliations, a no-silent-result-loss guard, no-double-booking,
  points reconciliation, Annexe C seed integrity, and shot-coordinate range checks. A failed test
  fails the run and fires a Slack alert.

## Tech stack

Airflow 3 (Astro Runtime) + astronomer-cosmos, dbt-core + dbt-duckdb (including a dbt python model
that runs the bracket third-place seeding), DuckDB, scikit-learn (offline xG training only),
Evidence.dev, GitHub Actions (CI + a schedule-aware Pages deploy), ruff + sqlfluff. For the
historical analysis: statsbombpy + socceraction.

## Run locally

Prerequisites: Python 3.12, Node 22+, Docker + the Astro CLI (for local Airflow). A football-data.org
API token in `.env` (`FOOTBALL_DATA_KEY`); FIFA needs no key.

```
make up        # local Airflow (Astro)
make dbt       # dbt seed + run + test
make evidence  # dashboard in dev mode
make lint      # ruff + sqlfluff
# CI runs hermetically on committed sample data (no API key needed)
```

The Euro 2024 analysis is standalone (own venv): `analysis/euro2024/.venv/bin/python
analysis/euro2024/run.py` reproduces its rankings from scratch. See `analysis/euro2024/README.md`
and `ml/README.md`.

## Honest limitations

- **Live xG coordinate frame: validated.** The model is trained on FIFA's 2022 (normalized) frame;
  the live 2026 frame was confirmed on the opening match (a 0-100 corner-origin frame) and the
  loader normalizes to it.
- **No xT/VAEP for live 2026** (FIFA's feed has no pass/carry events); those run only on the
  historical StatsBomb analysis.
- The FIFA API is undocumented; the pipeline is defensive (retries, schema tolerance, polite
  caching) and credits FIFA as the source without implying affiliation.

## License

Personal portfolio project. Data: FIFA (api.fifa.com) and football-data.org; historical events from
StatsBomb open data. Not affiliated with FIFA.
