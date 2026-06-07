# Astro Runtime base image (bundles Airflow 3.x). Pinned to the Airflow 3.2 line
# (3.2-2 stable as of 2026-06; 3.2-1 was restricted by Astronomer). Phase 0
# `astro dev init` will reconcile this to the CLI's current default if newer.
FROM quay.io/astronomer/astro-runtime:3.2-2

# requirements.txt is installed automatically by the Astro Runtime build.
