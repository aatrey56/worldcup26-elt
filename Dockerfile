# Astro Runtime base image (bundles Airflow 3.x). Pinned to the Airflow 3.2 line
# (3.2-2 stable as of 2026-06; 3.2-1 was restricted by Astronomer).
FROM quay.io/astronomer/astro-runtime:3.2-2

# Absolute warehouse path inside the container. Both the load task and dbt read
# DUCKDB_PATH; setting it here (and NOT in .env) keeps the host path from leaking
# into the container. include/data is bind-mounted, so this file is shared with
# the host, which is how the local dashboard sees the orchestrated output.
ENV DUCKDB_PATH=/usr/local/airflow/include/data/warehouse.duckdb

# Install dbt into an isolated virtualenv (dbt and Airflow can have conflicting
# dependencies) and pre-install dbt packages so Cosmos does not need network at
# parse time. Cosmos runs dbt via ExecutionConfig(dbt_executable_path=...).
RUN python -m venv dbt_venv && \
    . dbt_venv/bin/activate && \
    pip install --no-cache-dir dbt-duckdb==1.10.1 && \
    (cd dbt && dbt deps) && \
    deactivate
