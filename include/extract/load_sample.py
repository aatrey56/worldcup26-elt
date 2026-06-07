"""Load committed sample API responses into the DuckDB raw schema.

This populates raw.fixtures and raw.standings from include/data/raw_sample/*.json
so dbt can build and CI stays hermetic without a live API key. The real
API-backed loader (Phase 1) lands the same raw shape from live responses.

Idempotent: re-running deletes-then-inserts on the natural key, so row counts
stay stable. Run with the project venv:  python -m include.extract.load_sample
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
    """Land one row per fixture: (fixture_id, payload JSON, loaded_at)."""
    fixtures = _load_json("fixtures.json")
    con.execute(
        """
        create table if not exists raw.fixtures (
            fixture_id bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    rows = [(f["fixture"]["id"], json.dumps(f), loaded_at) for f in fixtures]
    ids = [r[0] for r in rows]
    con.executemany("delete from raw.fixtures where fixture_id = ?", [(i,) for i in ids])
    con.executemany("insert into raw.fixtures values (?, ?, ?)", rows)
    return len(rows)


def load_standings(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> int:
    """Explode nested standings into one row per (team_id, group_label)."""
    payloads = _load_json("standings.json")
    con.execute(
        """
        create table if not exists raw.standings (
            team_id     bigint,
            group_label varchar,
            payload     json,
            loaded_at   timestamp,
            primary key (team_id, group_label)
        )
        """
    )
    rows: list[tuple] = []
    for block in payloads:
        for group in block["league"]["standings"]:
            for entry in group:
                rows.append(
                    (
                        entry["team"]["id"],
                        entry["group"],
                        json.dumps(entry),
                        loaded_at,
                    )
                )
    keys = [(r[0], r[1]) for r in rows]
    con.executemany(
        "delete from raw.standings where team_id = ? and group_label = ?", keys
    )
    con.executemany("insert into raw.standings values (?, ?, ?, ?)", rows)
    return len(rows)


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(timezone.utc)
    logger.info("loading sample raw data into %s", db)
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        n_fix = load_fixtures(con, loaded_at)
        n_std = load_standings(con, loaded_at)
        logger.info("raw.fixtures: %d rows, raw.standings: %d rows", n_fix, n_std)
    finally:
        con.close()


if __name__ == "__main__":
    main()
