"""Phase 1 live loader: land football-data.org (v4) into the DuckDB raw schema.

Fetches World Cup matches and standings via FootballDataClient and lands them
into the existing raw table shapes that staging depends on:

    raw.fixtures(fixture_id BIGINT primary key, payload JSON, loaded_at TIMESTAMP)
        one row per match, payload = the full match object.
    raw.standings(team_id BIGINT primary key, payload JSON, loaded_at TIMESTAMP)
        one row per team from the TOTAL standings table only, payload = the
        table row with the parent entry's "group" injected (may be null).

The raw-table DDL, idempotent full-snapshot replace, row shaping, the legacy
schema migration, and payload validation all live in include.extract.raw_tables
and are shared with the sample loader. Run with the project venv after .env:

    set -a; . ./.env; set +a
    python -m include.extract.load_raw
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import requests

from include.extract.base_client import ApiClientError, TransientApiError
from include.extract.football_data import FootballDataClient
from include.extract.raw_tables import (
    RawContractError,
    align_standings_schema,
    replace_fixtures,
    replace_standings,
    validate_matches,
)

# football-data.org is the FALLBACK source (FIFA is primary). A failure to load
# it must NOT abort the build and take down the FIFA-driven live update, so these
# error classes are caught and degrade to FIFA-only rather than raising. A genuine
# programming error (anything not in this set) still fails loudly.
FOOTBALL_DATA_SOFT_ERRORS = (
    requests.exceptions.RequestException,  # connection drop, timeout, etc.
    ApiClientError,  # FootballDataError (bad/missing key, 4xx)
    TransientApiError,  # 5xx / rate-limit after retries
    RawContractError,  # provider changed shape / empty feed
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_raw")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "include" / "data" / "warehouse.duckdb"

# football-data.org free tier allows 10 calls/min. We make only 2 calls, but we
# respect the limit by sleeping to the next minute if the client surfaces a low
# remaining count just before a call.
RATE_LIMIT_FLOOR = 2


def _db_path() -> str:
    return os.environ.get("DUCKDB_PATH", str(DEFAULT_DB))


def _competition() -> str:
    return os.environ.get("WC_COMPETITION", "WC")


def _season() -> int:
    return int(os.environ.get("WC_SEASON", "2026"))


def _throttle_if_low(client: FootballDataClient) -> None:
    """Sleep until the next minute if the provider reports few calls remaining.

    The client logs X-Requests-Available-Minute on every request. We expose it
    via client.requests_remaining (set after the last call). If it is at or
    below RATE_LIMIT_FLOOR we wait out the current minute window so we never
    trip the 10 calls/min free limit the provider asked us to respect.
    """
    remaining = getattr(client, "requests_remaining", None)
    if remaining is not None and remaining <= RATE_LIMIT_FLOOR:
        logger.warning(
            "only %s calls remaining this minute, sleeping 60s to be safe",
            remaining,
        )
        time.sleep(60)


def load_fixtures(
    con: duckdb.DuckDBPyConnection, client: FootballDataClient, loaded_at: datetime
) -> int:
    """Land one row per match: (fixture_id, payload JSON, loaded_at)."""
    _throttle_if_low(client)
    response = client.get_matches(_competition(), _season(), use_cache=False)
    matches: list[dict[str, Any]] = validate_matches(response.get("matches"))
    return replace_fixtures(con, matches, loaded_at)


def load_standings(
    con: duckdb.DuckDBPyConnection, client: FootballDataClient, loaded_at: datetime
) -> int:
    """Land one row per team from the TOTAL standings table only.

    payload is the table row, with the parent entry's "group" injected (so the
    auxiliary stg_standings model can read a group_label even though the live
    feed nests it one level up). group is null pre-tournament.
    """
    _throttle_if_low(client)
    response = client.get_standings(_competition(), _season(), use_cache=False)
    entries: list[dict[str, Any]] = response.get("standings", [])

    table_rows: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "TOTAL":
            continue
        group = entry.get("group")
        for table_row in entry.get("table", []):
            row = dict(table_row)
            row["group"] = group
            table_rows.append(row)

    return replace_standings(con, table_rows, loaded_at)


def _ensure_raw_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create empty raw.fixtures/raw.standings shells if absent.

    Guarantees the tables staging reads always exist, so when the football-data
    fetch fails the pipeline degrades cleanly to FIFA-only (empty fallback tables)
    instead of dbt erroring on a missing relation. On a persistent warehouse any
    existing rows are left untouched (create-if-not-exists).
    """
    con.execute(
        "create table if not exists raw.fixtures "
        "(fixture_id bigint primary key, payload json, loaded_at timestamp)"
    )
    con.execute(
        "create table if not exists raw.standings "
        "(team_id bigint primary key, payload json, loaded_at timestamp)"
    )


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(UTC)
    logger.info("loading live raw data into %s", db)
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        align_standings_schema(con)
        _ensure_raw_tables(con)
        try:
            client = FootballDataClient()
            n_fix = load_fixtures(con, client, loaded_at)
            n_std = load_standings(con, client, loaded_at)
            logger.info("raw.fixtures: %d rows, raw.standings: %d rows", n_fix, n_std)
        except FOOTBALL_DATA_SOFT_ERRORS as exc:
            # football-data is the fallback; FIFA (loaded next) is the live source
            # of truth. Do not fail the build on a fallback outage - log loudly and
            # leave the raw tables as they are (empty on a fresh warehouse, prior
            # data on a persistent one). The pipeline runs FIFA-only this cycle.
            logger.warning(
                "football-data load failed (%s: %s); continuing FIFA-only",
                type(exc).__name__,
                exc,
            )
    finally:
        con.close()


if __name__ == "__main__":
    main()
