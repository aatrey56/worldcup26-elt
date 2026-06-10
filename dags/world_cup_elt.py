"""World Cup 2026 ELT DAG.

Daily pipeline: extract+load live data from football-data.org into the DuckDB raw
schema, then run the dbt build (models + tests) via Cosmos so every model and
test is its own Airflow task, then a publish placeholder.

DuckDB is single-writer, so the DAG is serialized (max_active_tasks=1 and
max_active_runs=1) to guarantee no two tasks open the warehouse for writing at
once. On any task failure a Slack alert fires (or logs if no webhook is set).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from callbacks import notify_slack_failure
from cosmos import (
    DbtTaskGroup,
    ExecutionConfig,
    ProfileConfig,
    ProjectConfig,
    RenderConfig,
)

from include.extract import load_fifa, load_raw

DBT_PROJECT_PATH = Path("/usr/local/airflow/dbt")
DBT_EXECUTABLE = "/usr/local/airflow/dbt_venv/bin/dbt"
DUCKDB_PATH = "/usr/local/airflow/include/data/warehouse.duckdb"

profile_config = ProfileConfig(
    profile_name="worldcup26",
    target_name="dev",
    profiles_yml_filepath=DBT_PROJECT_PATH / "profiles.yml",
)

project_config = ProjectConfig(
    dbt_project_path=DBT_PROJECT_PATH,
    env_vars={"DUCKDB_PATH": DUCKDB_PATH},
)

execution_config = ExecutionConfig(dbt_executable_path=DBT_EXECUTABLE)

default_args = {
    "retries": 1,
    "on_failure_callback": notify_slack_failure,
}

with DAG(
    dag_id="world_cup_elt",
    description="Extract live WC 2026 data, load to DuckDB, build + test via dbt (Cosmos).",
    schedule="@daily",
    start_date=datetime(2026, 6, 10),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,  # DuckDB single-writer: never two writers at once
    default_args=default_args,
    tags=["worldcup", "elt", "dbt", "cosmos"],
) as dag:

    extract_load_raw = PythonOperator(
        task_id="extract_load_raw",
        python_callable=load_raw.main,
    )

    # FIFA's free public API (shot coordinates, events, lineups, top scorers).
    # No key. Runs after football-data so the two never write DuckDB at once
    # (DuckDB is single-writer; the DAG is serialized via max_active_tasks=1).
    extract_load_fifa = PythonOperator(
        task_id="extract_load_fifa",
        python_callable=load_fifa.main,
    )

    dbt_build = DbtTaskGroup(
        group_id="dbt_build",
        project_config=project_config,
        profile_config=profile_config,
        execution_config=execution_config,
        render_config=RenderConfig(),
    )

    publish_dashboard = EmptyOperator(task_id="publish_dashboard")

    extract_load_raw >> extract_load_fifa >> dbt_build >> publish_dashboard
