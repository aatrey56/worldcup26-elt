"""Shared raw-loading helpers for the live and sample loaders.

Both load_raw (live, football-data.org) and load_sample (committed JSON) land
into the identical raw table shapes that dbt staging depends on:

    raw.fixtures(fixture_id BIGINT primary key, payload JSON, loaded_at TIMESTAMP)
    raw.standings(team_id BIGINT primary key, payload JSON, loaded_at TIMESTAMP)

This module owns the DDL, the delete-then-insert idempotency (full-snapshot
replace), the (id, json.dumps, loaded_at) row shaping, the legacy-schema
migration, and a lightweight payload-shape validation so a provider change fails
loudly at the load boundary instead of as nulls deep in dbt.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import duckdb

logger = logging.getLogger("raw_tables")

# Keys every match object must carry. Missing keys mean the provider shape
# changed (or a record is malformed) and we want a loud failure at the boundary.
REQUIRED_MATCH_KEYS = ("id", "utcDate", "status", "homeTeam", "awayTeam", "score")


class RawContractError(RuntimeError):
    """Raised when the provider payload violates the expected raw contract."""


def validate_matches(matches: Any) -> list[dict[str, Any]]:
    """Validate the matches list shape before landing.

    Checks the list is present and non-empty and that every match carries the
    required keys. Raises RawContractError (after logging) on any violation so a
    malformed feed fails fast rather than corrupting the load.
    """
    if not isinstance(matches, list) or not matches:
        logger.error("matches contract violation: expected a non-empty list, got %r", type(matches))
        raise RawContractError("matches payload is missing or empty")
    for idx, match in enumerate(matches):
        if not isinstance(match, dict):
            logger.error("matches[%d] is not an object: %r", idx, type(match))
            raise RawContractError(f"match at index {idx} is not an object")
        missing = [k for k in REQUIRED_MATCH_KEYS if k not in match]
        if missing:
            logger.error(
                "matches[%d] (id=%s) missing required keys: %s",
                idx,
                match.get("id"),
                missing,
            )
            raise RawContractError(f"match at index {idx} missing keys: {missing}")
    ids = [match["id"] for match in matches]
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for match_id in ids:
        if match_id in seen and match_id not in duplicates:
            duplicates.append(match_id)
        seen.add(match_id)
    if duplicates:
        logger.error("matches contract violation: duplicate match id(s): %s", duplicates)
        raise RawContractError(f"matches payload contains duplicate id(s): {duplicates}")
    return matches


def align_standings_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Drop a legacy raw.standings table if it has the old wider schema.

    The original API-Football loader created raw.standings with a group_label
    column. The football-data.org shape stores group inside the payload, so we
    rebuild the table with the (team_id, payload, loaded_at) schema staging now
    expects. Safe because the loaders fully repopulate it.
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


def _replace_rows(
    con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple[int, str, datetime]]
) -> int:
    """Full-snapshot replace: clear the table then insert rows.

    Delete-then-insert keeps the load idempotent (stable row counts) and
    prevents stale rows (sample data, or records dropped upstream) from
    lingering and fanning out downstream joins. executemany sends the whole
    batch through one prepared statement, so it is a single bulk call rather
    than N separate round-trips.
    """
    con.execute(f"delete from {table}")
    if rows:
        con.executemany(f"insert into {table} values (?, ?, ?)", rows)
    return len(rows)


def replace_fixtures(
    con: duckdb.DuckDBPyConnection, matches: list[dict[str, Any]], loaded_at: datetime
) -> int:
    """Ensure raw.fixtures exists and replace it with one row per match."""
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
    return _replace_rows(con, "raw.fixtures", rows)


def replace_standings(
    con: duckdb.DuckDBPyConnection, table_rows: list[dict[str, Any]], loaded_at: datetime
) -> int:
    """Ensure raw.standings exists and replace it with one row per team.

    table_rows are the final per-team payloads (TOTAL standings rows with group
    already injected), exactly as both loaders store them.
    """
    con.execute(
        """
        create table if not exists raw.standings (
            team_id    bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    rows = [(int(r["team"]["id"]), json.dumps(r), loaded_at) for r in table_rows]
    return _replace_rows(con, "raw.standings", rows)
