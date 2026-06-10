"""Load committed sample API responses into the DuckDB raw schema.

This populates raw.fixtures and raw.standings from include/data/raw_sample/*.json
so dbt can build and CI stays hermetic without a live API key. The samples use
the football-data.org v4 match/standings shape, identical to what the live
loader (include/extract/load_raw.py) lands, so both paths exercise the same
staging logic.

  fixtures.json   list of football-data.org v4 match objects.
  standings.json  list of TOTAL standings table-rows, each with group injected
                  (the exact row shape the live loader stores).

Idempotent: delete-then-insert on the primary key, so row counts stay stable.
Run with the project venv:  python -m include.extract.load_sample
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_sample")

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "include" / "data" / "raw_sample"
DEFAULT_DB = REPO_ROOT / "include" / "data" / "warehouse.duckdb"


def _db_path() -> str:
    return os.environ.get("DUCKDB_PATH", str(DEFAULT_DB))


def _load_json(name: str) -> list[dict]:
    with (SAMPLE_DIR / name).open() as fh:
        return json.load(fh)


def load_fixtures(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> int:
    """Land one row per match: (fixture_id, payload JSON, loaded_at)."""
    matches = _load_json("fixtures.json")
    con.execute(
        """
        create table if not exists raw.fixtures (
            fixture_id bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    rows = [(int(m["id"]), json.dumps(m), loaded_at) for m in matches]
    # Full-snapshot replace so the sample set fully owns the table and switching
    # between sample and live loads never leaves orphan rows behind.
    con.execute("delete from raw.fixtures")
    con.executemany("insert into raw.fixtures values (?, ?, ?)", rows)
    return len(rows)


def load_standings(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> int:
    """Land one row per team: (team_id, payload JSON, loaded_at).

    payload is the TOTAL standings table-row with group injected.
    """
    rows_json = _load_json("standings.json")
    con.execute(
        """
        create table if not exists raw.standings (
            team_id    bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    rows = [(int(r["team"]["id"]), json.dumps(r), loaded_at) for r in rows_json]
    # Full-snapshot replace, same rationale as fixtures.
    con.execute("delete from raw.standings")
    con.executemany("insert into raw.standings values (?, ?, ?)", rows)
    return len(rows)


def _align_standings_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Drop a legacy raw.standings table if it has the old wider schema.

    The original API-Football loader created raw.standings with a group_label
    column. The football-data.org shape stores group inside the payload, so we
    rebuild the table with the (team_id, payload, loaded_at) schema staging now
    expects. Safe because load_standings fully repopulates it.
    """
    exists = con.execute(
        "select count(*) from information_schema.tables "
        "where table_schema = 'raw' and table_name = 'standings'"
    ).fetchone()[0]
    if not exists:
        return
    cols = [
        r[0]
        for r in con.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'raw' and table_name = 'standings'"
        ).fetchall()
    ]
    if "group_label" in cols:
        logger.info("dropping legacy raw.standings (had group_label column)")
        con.execute("drop table raw.standings")


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(timezone.utc)
    logger.info("loading sample raw data into %s", db)
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        _align_standings_schema(con)
        n_fix = load_fixtures(con, loaded_at)
        n_std = load_standings(con, loaded_at)
        logger.info("raw.fixtures: %d rows, raw.standings: %d rows", n_fix, n_std)
    finally:
        con.close()


if __name__ == "__main__":
    main()
