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


# --- FIFA raw tables (Phase 1 shot-level ingest) -----------------------------
# The FIFA public API (api.fifa.com) is undocumented, so validation here is
# deliberately lighter than the football-data contract: we assert only the
# minimum structural shape (a list of objects, ids present where we make them a
# primary key) and let schema-tolerant parsing in the loader/staging produce
# nulls for anything else. Every match/topscorer object is stored whole as JSON.

# Keys every FIFA calendar match must carry to be landable (it is our pk source).
REQUIRED_FIFA_MATCH_KEYS = ("IdMatch",)


def validate_fifa_matches(matches: Any) -> list[dict[str, Any]]:
    """Validate the FIFA calendar match list before landing.

    Empty-safe: an empty list is allowed (pre-tournament there can be 0 matches
    in some calls, though WC 2026 currently returns 104). We require a list of
    objects each carrying IdMatch, since that is the primary key.

    DEDUP (F5): raw.fifa_matches makes IdMatch its primary key, so a calendar
    that repeats an IdMatch (seen on FIFA feeds) would crash the load on a PK
    violation. Mirroring validate_matches, we drop duplicate IdMatch (keeping the
    first occurrence) and log it rather than failing.
    """
    if matches is None:
        return []
    if not isinstance(matches, list):
        logger.error("fifa matches contract violation: expected a list, got %r", type(matches))
        raise RawContractError("fifa matches payload is not a list")
    deduped: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for idx, match in enumerate(matches):
        if not isinstance(match, dict):
            logger.error("fifa matches[%d] is not an object: %r", idx, type(match))
            raise RawContractError(f"fifa match at index {idx} is not an object")
        missing = [k for k in REQUIRED_FIFA_MATCH_KEYS if k not in match or match[k] is None]
        if missing:
            logger.error(
                "fifa matches[%d] missing required keys: %s", idx, missing
            )
            raise RawContractError(f"fifa match at index {idx} missing keys: {missing}")
        match_id = match["IdMatch"]
        if match_id in seen:
            logger.warning(
                "fifa matches[%d] duplicate IdMatch %r, keeping first occurrence",
                idx,
                match_id,
            )
            continue
        seen.add(match_id)
        deduped.append(match)
    return deduped


def replace_fifa_matches(
    con: duckdb.DuckDBPyConnection, matches: list[dict[str, Any]], loaded_at: datetime
) -> int:
    """Ensure raw.fifa_matches exists and replace it with one row per match."""
    con.execute(
        """
        create table if not exists raw.fifa_matches (
            match_id   bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    # F6: skip-and-log matches whose IdMatch is not int-coercible (placeholder/
    # TBD knockout slots) rather than raising ValueError and aborting the load.
    rows: list[tuple[int, str, datetime]] = []
    for m in matches:
        try:
            match_id = int(m["IdMatch"])
        except (ValueError, TypeError):
            logger.warning(
                "fifa match has non-int-coercible IdMatch %r, skipping",
                m.get("IdMatch"),
            )
            continue
        rows.append((match_id, json.dumps(m), loaded_at))
    return _replace_rows(con, "raw.fifa_matches", rows)


def replace_fifa_events(
    con: duckdb.DuckDBPyConnection,
    events: list[tuple[int, int, dict[str, Any]]],
    loaded_at: datetime,
) -> int:
    """Ensure raw.fifa_events exists and replace it with one row per event.

    events is a list of (match_id, event_idx, enriched_event_payload). The
    payload already carries loader-computed normalized coordinates and geometry
    (x_norm, y_norm, is_goal, is_penalty, shot_distance, shot_angle) so dbt
    staging stays a clean 1:1 projection. Empty-safe: with no finished matches
    this is simply an empty table.
    """
    con.execute(
        """
        create table if not exists raw.fifa_events (
            match_id   bigint,
            event_idx  integer,
            payload    json,
            loaded_at  timestamp,
            primary key (match_id, event_idx)
        )
        """
    )
    rows = [
        (int(match_id), int(event_idx), json.dumps(payload), loaded_at)
        for match_id, event_idx, payload in events
    ]
    con.execute("delete from raw.fifa_events")
    if rows:
        con.executemany("insert into raw.fifa_events values (?, ?, ?, ?)", rows)
    return len(rows)


def replace_fifa_lineups(
    con: duckdb.DuckDBPyConnection,
    lineups: list[tuple[int, int, dict[str, Any]]],
    loaded_at: datetime,
) -> int:
    """Ensure raw.fifa_lineups exists and replace it with one row per appearance.

    lineups is a list of (player_id, match_id, player_payload). The grain is one
    row per (player_id, match_id): a player appears once per match they were named
    in. player_payload is the FIFA lineup player object (carrying IdPlayer, IdTeam,
    PlayerName, Position, etc.). The primary key (player_id, match_id) keeps the
    load idempotent and lets dim_fifa_player dedup a player across matches.

    DEDUP: a player can appear at most once per match in a lineup, but we defend
    against a feed that repeats an entry by keeping the first occurrence per
    (player_id, match_id). Entries with a non-int-coercible id are skipped and
    logged. Empty-safe: with no played matches this is simply an empty table.
    """
    con.execute(
        """
        create table if not exists raw.fifa_lineups (
            player_id  bigint,
            match_id   bigint,
            payload    json,
            loaded_at  timestamp,
            primary key (player_id, match_id)
        )
        """
    )
    rows: list[tuple[int, int, str, datetime]] = []
    seen: set[tuple[int, int]] = set()
    for player_id_raw, match_id_raw, payload in lineups:
        try:
            player_id = int(player_id_raw)
            match_id = int(match_id_raw)
        except (ValueError, TypeError):
            logger.warning(
                "fifa lineup entry has non-int id(s) player=%r match=%r, skipping",
                player_id_raw,
                match_id_raw,
            )
            continue
        key = (player_id, match_id)
        if key in seen:
            logger.warning(
                "fifa lineup duplicate (player=%s, match=%s), keeping first",
                player_id,
                match_id,
            )
            continue
        seen.add(key)
        rows.append((player_id, match_id, json.dumps(payload), loaded_at))
    con.execute("delete from raw.fifa_lineups")
    if rows:
        con.executemany("insert into raw.fifa_lineups values (?, ?, ?, ?)", rows)
    return len(rows)


def replace_fifa_topscorers(
    con: duckdb.DuckDBPyConnection, players: list[dict[str, Any]], loaded_at: datetime
) -> int:
    """Ensure raw.fifa_topscorers exists and replace it with one row per player.

    players are PlayerStatsList entries from the topscorers feed; the primary key
    is PlayerInfo.IdPlayer. Entries without a resolvable player id are skipped
    (logged) rather than failing the load. Empty-safe.
    """
    con.execute(
        """
        create table if not exists raw.fifa_topscorers (
            player_id  bigint primary key,
            payload    json,
            loaded_at  timestamp
        )
        """
    )
    rows: list[tuple[int, str, datetime]] = []
    seen: set[int] = set()
    for player in players or []:
        # F4: PlayerStatsList entries may be null/non-dict (and an absent feed,
        # e.g. season 285023, yields a null body the caller passes as []). Skip
        # anything that is not a dict instead of calling .get() on it.
        if not isinstance(player, dict):
            logger.warning("fifa topscorer entry is not an object (%r), skipping", type(player))
            continue
        player_info = player.get("PlayerInfo")
        pid_raw = player_info.get("IdPlayer") if isinstance(player_info, dict) else None
        if pid_raw is None:
            logger.warning("fifa topscorer entry missing PlayerInfo.IdPlayer, skipping")
            continue
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            logger.warning("fifa topscorer has non-integer IdPlayer %r, skipping", pid_raw)
            continue
        if pid in seen:
            continue
        seen.add(pid)
        rows.append((pid, json.dumps(player), loaded_at))
    return _replace_rows(con, "raw.fifa_topscorers", rows)
