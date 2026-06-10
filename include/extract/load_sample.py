"""Load committed sample API responses into the DuckDB raw schema.

This populates raw.fixtures and raw.standings from include/data/raw_sample/*.json
so dbt can build and CI stays hermetic without a live API key. The samples use
the football-data.org v4 match/standings shape, identical to what the live
loader (include/extract/load_raw.py) lands, so both paths exercise the same
staging logic.

  fixtures.json   list of football-data.org v4 match objects.
  standings.json  list of TOTAL standings table-rows, each with group injected
                  (the exact row shape the live loader stores).

The raw-table DDL, idempotent full-snapshot replace, row shaping, the legacy
schema migration, and payload validation are shared with the live loader via
include.extract.raw_tables. Run with the project venv:

    python -m include.extract.load_sample
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from include.extract.raw_tables import (
    RawContractError,
    align_standings_schema,
    replace_fifa_events,
    replace_fifa_lineups,
    replace_fifa_matches,
    replace_fifa_topscorers,
    replace_fixtures,
    replace_standings,
    validate_fifa_matches,
    validate_matches,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_sample")

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "include" / "data" / "raw_sample"
DEFAULT_DB = REPO_ROOT / "include" / "data" / "warehouse.duckdb"


def _db_path() -> str:
    return os.environ.get("DUCKDB_PATH", str(DEFAULT_DB))


def _load_json(name: str) -> list[dict[str, Any]]:
    with (SAMPLE_DIR / name).open() as fh:
        return json.load(fh)


def load_fixtures(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> int:
    """Land one row per match: (fixture_id, payload JSON, loaded_at)."""
    matches = validate_matches(_load_json("fixtures.json"))
    return replace_fixtures(con, matches, loaded_at)


def load_standings(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> int:
    """Land one row per team: (team_id, payload JSON, loaded_at).

    payload is the TOTAL standings table-row with group injected.
    """
    table_rows = _load_json("standings.json")
    return replace_standings(con, table_rows, loaded_at)


def load_fifa(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> dict[str, int]:
    """Land the committed FIFA samples (real, trimmed 2022 data).

    fifa_matches.json    list of FIFA calendar match objects.
    fifa_events.json     list of {match_id, event_idx, payload} where payload is
                         the loader-enriched event (normalized coords + geometry),
                         exactly the row shape the live FIFA loader stores.
    fifa_lineups.json    list of {match_id, player_id, payload} where payload is a
                         FIFA lineup player object (IdPlayer/IdTeam/PlayerName/
                         Position): the player-dimension source.
    fifa_topscorers.json list of PlayerStatsList entries.
    Keeps dbt build hermetic for the FIFA staging models in CI.
    """
    matches = validate_fifa_matches(_load_json("fifa_matches.json"))
    n_matches = replace_fifa_matches(con, matches, loaded_at)

    event_rows = _load_json("fifa_events.json")
    events = [(r["match_id"], r["event_idx"], r["payload"]) for r in event_rows]
    n_events = replace_fifa_events(con, events, loaded_at)

    lineup_rows = _load_json("fifa_lineups.json")
    lineups = [(r["player_id"], r["match_id"], r["payload"]) for r in lineup_rows]
    n_lineups = replace_fifa_lineups(con, lineups, loaded_at)

    players = _load_json("fifa_topscorers.json")
    n_scorers = replace_fifa_topscorers(con, players, loaded_at)
    return {
        "fifa_matches": n_matches,
        "fifa_events": n_events,
        "fifa_lineups": n_lineups,
        "fifa_topscorers": n_scorers,
    }


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(UTC)
    logger.info("loading sample raw data into %s", db)
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        align_standings_schema(con)
        n_fix = load_fixtures(con, loaded_at)
        n_std = load_standings(con, loaded_at)
        logger.info("raw.fixtures: %d rows, raw.standings: %d rows", n_fix, n_std)
        # F7: FIFA sample loading is decoupled from the football-data hermetic
        # path. The football-data sample load above is the critical CI contract;
        # a missing/malformed FIFA sample must NOT break it. We therefore land
        # FIFA samples best-effort and log-and-continue on failure rather than
        # aborting (the FIFA staging models are empty-safe without these rows).
        try:
            fifa_counts = load_fifa(con, loaded_at)
            logger.info("FIFA sample row counts: %s", fifa_counts)
        except (OSError, ValueError, KeyError, TypeError, RawContractError) as exc:
            logger.warning(
                "FIFA sample load failed (%s); continuing so the football-data "
                "hermetic sample load is preserved",
                exc,
            )
    finally:
        con.close()


if __name__ == "__main__":
    main()
