# Incremental load and idempotent backfill

`fct_result` is the one incremental model in the pipeline. This doc shows the two
patterns it demonstrates and how to reproduce them. All commands run from `dbt/`
with the project venv and `DUCKDB_PATH` pointing at the warehouse.

```bash
cd dbt
export DUCKDB_PATH="$(pwd)/../include/data/warehouse.duckdb"
DBT=../.venv/bin/dbt
```

## How the incremental model works

`fct_result` (see `models/marts/fct_result.sql`):

- `materialized='incremental'`, `unique_key='match_key'`,
  `incremental_strategy='delete+insert'`.
- DuckDB has no native `MERGE`, so `delete+insert` on `unique_key` gives upsert
  semantics: dbt deletes the incoming `match_key`s from the target, then inserts
  the new rows. A corrected score replaces its row and never duplicates it.
- Incremental predicate: on incremental runs we only pull source rows whose raw
  load timestamp is newer than the newest one already loaded:

  ```sql
  {% if is_incremental() %}
  where source_loaded_at > (select max(source_loaded_at) from {{ this }})
  {% endif %}
  ```

  `source_loaded_at` flows from `raw.fixtures.loaded_at` through staging and
  intermediate. The loader stamps a fresh `loaded_at` whenever a fixture is
  (re)landed, so this predicate captures BOTH brand-new finished matches AND
  corrections to already-loaded scores, while skipping unchanged rows.

## Pattern 1: idempotent re-run (no source change)

Re-running with no new data changes nothing: no duplicates, stable row count.

```bash
$DBT run --select fct_result --profiles-dir .   # run once
$DBT run --select fct_result --profiles-dir .   # run again
# row count is identical both times (the predicate matches zero new rows)
```

Observed: row count stayed at 2 across re-runs.

## Pattern 2: a corrected score updates exactly one row

Simulate a corrected fixture arriving (new score, fresh `loaded_at`):

```python
# correct fixture 9001 from 2-1 to 3-1 and restamp loaded_at
import duckdb, json, datetime
c = duckdb.connect("include/data/warehouse.duckdb")
p = json.loads(c.execute("select payload from raw.fixtures where fixture_id=9001").fetchone()[0])
p["goals"]["home"] = 3; p["score"]["fulltime"]["home"] = 3
c.execute("update raw.fixtures set payload=?, loaded_at=? where fixture_id=9001",
          [json.dumps(p), datetime.datetime.now(datetime.timezone.utc)])
```

```bash
$DBT run --select fct_result --profiles-dir .
```

Observed: the Mexico row changed 2-1 to 3-1 (`home_win`), the other finished
match (1-1 draw) was untouched, and the row count stayed at 2. Only the changed
match was reprocessed.

## Backfilling the group stage

The 104-match schedule is a static dimension (`dim_match`) seeded from
`schedule_seed.csv`, so it is complete before any match is played. Results are
loaded into the incremental `fct_result` as fixtures finish. To backfill from
scratch and prove it is safe to repeat:

```bash
# (re)land the raw fixtures, then build everything
python -m include.extract.load_sample          # or the live loader in Phase 1
cd dbt
$DBT build --full-refresh --profiles-dir .      # clean rebuild
$DBT build --profiles-dir .                      # re-run: still 46 PASS, no dupes
```

`--full-refresh` rebuilds the incremental table from scratch (use it when the
model schema changes). A plain `dbt build` afterward is the idempotent path the
DAG uses in production.
