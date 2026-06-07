.PHONY: up down restart lint seed dbt test backfill docs evidence clean

# --- Airflow (Astro) ---
up:            ## start local Airflow
	astro dev start

down:          ## stop local Airflow
	astro dev stop

restart:       ## restart local Airflow
	astro dev restart

# --- linting ---
lint:          ## run ruff + sqlfluff
	ruff check .
	sqlfluff lint dbt/models

# --- dbt (run from the dbt/ dir) ---
seed:          ## load seeds into the warehouse
	cd dbt && dbt seed

dbt:           ## full dbt build: seed + run + test
	cd dbt && dbt build

test:          ## dbt tests only
	cd dbt && dbt test

docs:          ## generate dbt docs
	cd dbt && dbt docs generate

backfill:      ## documented idempotent backfill run (see docs/backfill.md)
	cd dbt && dbt run --select fct_result

# --- serving ---
evidence:      ## run the Evidence dashboard in dev mode
	cd reports && npm run sources && npm run dev

clean:         ## remove local warehouse + dbt artifacts (does not touch raw cache)
	rm -f include/data/*.duckdb include/data/*.duckdb.wal
	rm -rf dbt/target dbt/dbt_packages dbt/logs
