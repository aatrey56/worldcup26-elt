"""Phase 1 FIFA loader: land shot-level data into the DuckDB raw schema.

Fetches the World Cup 2026 calendar via FIFAClient and lands it, then for each
match whose status indicates it has been played or is live, fetches the event
timeline and lands its events. Also lands the season top scorers. Targets:

    raw.fifa_matches(match_id BIGINT pk, payload JSON, loaded_at TIMESTAMP)
        one row per calendar match, payload = the full calendar match object.
    raw.fifa_events(match_id BIGINT, event_idx INT, payload JSON, loaded_at,
                    primary key (match_id, event_idx))
        one row per timeline event. The payload is the raw FIFA event ENRICHED
        with loader-computed fields so dbt staging stays a clean 1:1 projection:
            x_norm, y_norm   coordinates normalized to a 0-1 frame (goal x=1,
                             y=0.5) via fifa.normalize_xy (scale + frame fix).
            event_desc       TypeLocalized[0].Description (the primary type map).
            is_shot          true for shot/goal/penalty-shot events.
            is_goal, is_penalty, shot_outcome   shot classification.
            shot_distance, shot_angle           xG geometry from x_norm/y_norm.
        Geometry is computed in the loader (Python) because the 0-1 normalization
        depends on a per-match scale decision that is awkward in pure SQL.
    raw.fifa_topscorers(player_id BIGINT pk, payload JSON, loaded_at TIMESTAMP)
        one row per PlayerStatsList entry, payload = the full player stats object.

EMPTY-SAFE: WC 2026 has zero finished matches right now, so raw.fifa_events is
simply empty and nothing errors. The DDL, idempotent replace, and validation are
shared with the other loaders via include.extract.raw_tables. Run:

    python -m include.extract.load_fifa                 # WC 2026 live (empty)
    FIFA_TEST_2022_FINAL=1 python -m include.extract.load_fifa   # 2022 final
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from include.extract.fifa import (
    WC_COMPETITION,
    WC_SEASON,
    FIFAClient,
    normalize_xy,
)
from include.extract.raw_tables import (
    replace_fifa_events,
    replace_fifa_matches,
    replace_fifa_topscorers,
    validate_fifa_matches,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_fifa")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "include" / "data" / "warehouse.duckdb"

# MatchStatus values that mean a timeline exists worth fetching: 0=played,
# 3/12=live (per the documented calendar shape).
PLAYED_OR_LIVE_STATUSES = frozenset({0, 3, 12})

# Polite delay between live timeline calls against the undocumented API.
THROTTLE_SECONDS = 0.4

# Known-good historical match for verification (2022 World Cup final).
TEST_2022_FINAL = {"season": 255711, "stage": 285077, "match": 400128145}

# Goal geometry in the normalized 0-1 frame. The attacked goal centre is at
# (1.0, 0.5). The goal mouth is 7.32m wide on a 68m-wide pitch -> 0.1076 of the
# y-axis, centred on 0.5, so the posts are at y = 0.5 +/- 0.0538.
GOAL_X = 1.0
GOAL_CENTER_Y = 0.5
GOAL_HALF_WIDTH = (7.32 / 68.0) / 2.0  # ~0.0538

# Event type descriptions (TypeLocalized[0].Description). "Penalty Awarded" is
# the award, NOT a shot, so it is excluded from shots.
SHOT_DESCRIPTIONS = frozenset(
    {"Attempt at Goal", "Goal!", "Penalty Goal", "Penalty missed"}
)
GOAL_DESCRIPTIONS = frozenset({"Goal!", "Penalty Goal"})
PENALTY_DESCRIPTIONS = frozenset({"Penalty Goal", "Penalty missed"})

# Substrings (case-insensitive) marking an own goal in an event description.
# Own goals are NOT shots/goals for the scoring player's own team, so they are
# excluded from is_shot/is_goal/is_penalty to avoid mis-attribution (F9).
OWN_GOAL_MARKERS = ("own goal",)

# SHOOTOUT EXCLUSION RULE (F1). Penalty-SHOOTOUT kicks are not open-play in-match
# shots and must not pollute shot/xG/penalty counts. The FIFA timeline marks the
# shootout with a distinct Period value: regulation/extra-time use Periods
# 3/5/7/9 (1st/2nd half, ET 1st/2nd), and the shootout is Period 11 (verified on
# the 2022 final: minutes 121'-126', eight Penalty Goal/missed events). We
# therefore exclude every event whose Period is in SHOOTOUT_PERIODS from the
# shot/goal/penalty flags. In-match penalties (e.g. the 2022 final's minute 23',
# 80', 118' spot-kicks in Periods 3/5/9) are retained.
SHOOTOUT_PERIODS = frozenset({11})


def _is_shootout(event: dict[str, Any]) -> bool:
    """True for penalty-shootout events (excluded from shots, see F1)."""
    return event.get("Period") in SHOOTOUT_PERIODS


def _is_own_goal(desc: str | None, event: dict[str, Any]) -> bool:
    """True if the event is an own goal (excluded from shots, see F9).

    Checks the type description and the free-text EventDescription for an
    own-goal marker so a goal credited to the wrong team is not counted as a
    normal shot/goal for the scoring player's side.
    """
    haystacks = [desc, event.get("EventDescription")]
    for text in haystacks:
        if isinstance(text, str):
            lowered = text.lower()
            if any(marker in lowered for marker in OWN_GOAL_MARKERS):
                return True
    return False


def _db_path() -> str:
    return os.environ.get("DUCKDB_PATH", str(DEFAULT_DB))


def _first_description(localized: Any) -> str | None:
    """Pull Description from a FIFA localized list like [{"Description": "..."}]."""
    if isinstance(localized, list) and localized:
        first = localized[0]
        if isinstance(first, dict):
            return first.get("Description")
    return None


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion; None on missing/non-int-coercible (F6).

    Placeholder/TBD knockout slots can carry non-numeric IdMatch/IdStage; we
    return None so the caller can skip-and-log instead of raising ValueError and
    aborting the whole load.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _as_float(value: Any) -> float | None:
    """Best-effort float coercion; None on missing/garbage (schema-tolerant)."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _shot_outcome(desc: str | None, is_goal: bool) -> str | None:
    """Best-effort shot outcome from the event type description.

    The FIFA timeline does not distinguish saved/blocked/off-target for open-play
    attempts, so "Attempt at Goal" that is not a goal is the catch-all "attempt".
    """
    if is_goal:
        return "goal"
    if desc == "Penalty missed":
        return "missed"
    if desc == "Attempt at Goal":
        return "attempt"
    return None


def _shot_geometry(
    x_norm: float | None, y_norm: float | None
) -> tuple[float | None, float | None]:
    """Compute (shot_distance, shot_angle) in the normalized 0-1 frame.

    shot_distance is the Euclidean distance from (x_norm, y_norm) to the goal
    centre (1.0, 0.5), in normalized units. shot_angle is the angle (radians)
    subtended by the goal mouth at the shot location, the standard xG geometry
    angle: angle = atan2(g * d, d^2 + (g^2 - p^2)) where g is the goal half-width,
    d is the perpendicular distance to the goal line (1 - x), and p is the lateral
    offset from the goal centre (y - 0.5). Wider/straighter shots get a larger
    angle. Returns (None, None) when coordinates are missing.
    """
    if x_norm is None or y_norm is None:
        return (None, None)
    dx = GOAL_X - x_norm
    dy = y_norm - GOAL_CENTER_Y
    distance = math.hypot(dx, dy)

    g = GOAL_HALF_WIDTH
    denom = dx * dx + (dy * dy - g * g)
    # dx = 1 - x_norm >= 0 after clamping, so atan2(2*g*dx, denom) is already in
    # [0, pi]; no wrap correction is needed (the old "if angle < 0" branch was
    # unreachable and would have been wrong if reached, so it is removed, F9).
    angle = math.atan2(2.0 * g * dx, denom)
    return (distance, angle)


def enrich_event(
    event: dict[str, Any],
    match_coords: list[tuple[float | None, float | None]],
) -> dict[str, Any]:
    """Return a copy of the event with loader-computed shot/geometry fields.

    match_coords is every (PositionX, PositionY) in the match, used by
    normalize_xy for the per-match scale decision. The enriched fields keep dbt
    staging a clean 1:1 read.
    """
    enriched = dict(event)
    desc = _first_description(event.get("TypeLocalized"))
    raw_x = _as_float(event.get("PositionX"))
    raw_y = _as_float(event.get("PositionY"))
    x_norm, y_norm = normalize_xy(raw_x, raw_y, match_coords)

    # Shootout kicks (F1) and own goals (F9) are not open-play in-match shots:
    # exclude them from every shot flag so they cannot pollute shot/xG/penalty
    # counts or be mis-attributed to the scoring player's team.
    excluded = _is_shootout(event) or _is_own_goal(desc, event)
    is_shot = desc in SHOT_DESCRIPTIONS and not excluded
    is_goal = desc in GOAL_DESCRIPTIONS and not excluded
    is_penalty = desc in PENALTY_DESCRIPTIONS and not excluded
    distance, angle = _shot_geometry(x_norm, y_norm)

    enriched["event_desc"] = desc
    enriched["x_norm"] = x_norm
    enriched["y_norm"] = y_norm
    enriched["is_shot"] = is_shot
    enriched["is_goal"] = is_goal
    enriched["is_penalty"] = is_penalty
    enriched["shot_outcome"] = _shot_outcome(desc, is_goal) if is_shot else None
    enriched["shot_distance"] = distance
    enriched["shot_angle"] = angle
    return enriched


def _match_coords(events: list[dict[str, Any]]) -> list[tuple[float | None, float | None]]:
    """Collect every (PositionX, PositionY) in a match for scale detection."""
    return [
        (_as_float(e.get("PositionX")), _as_float(e.get("PositionY")))
        for e in events
    ]


def load_calendar(
    con: duckdb.DuckDBPyConnection, client: FIFAClient, loaded_at: datetime
) -> list[dict[str, Any]]:
    """Fetch and land the WC 2026 calendar; return the validated match list."""
    response = client.get_calendar(use_cache=False)
    matches = validate_fifa_matches(response.get("Results"))
    n = replace_fifa_matches(con, matches, loaded_at)
    logger.info("raw.fifa_matches: %d rows", n)
    return matches


def load_events(
    con: duckdb.DuckDBPyConnection,
    client: FIFAClient,
    matches: list[dict[str, Any]],
    loaded_at: datetime,
    competition: int = WC_COMPETITION,
    season: int = WC_SEASON,
) -> int:
    """Fetch timelines for played/live matches and land enriched events.

    Empty-safe: with zero played matches this lands an empty table and never
    calls the timeline endpoint.
    """
    rows: list[tuple[int, int, dict[str, Any]]] = []
    played = [m for m in matches if m.get("MatchStatus") in PLAYED_OR_LIVE_STATUSES]
    logger.info("%d of %d matches are played/live (timeline candidates)", len(played), len(matches))

    for match in played:
        match_id = _coerce_int(match.get("IdMatch"))
        stage = _coerce_int(match.get("IdStage"))
        if match_id is None or stage is None:
            # F6: placeholder/TBD knockout slots have non-int-coercible ids.
            # Skip and log rather than aborting the whole load on ValueError.
            logger.warning(
                "skipping timeline for match with non-int-coercible "
                "IdMatch=%r / IdStage=%r",
                match.get("IdMatch"),
                match.get("IdStage"),
            )
            continue
        # F8: do NOT serve played/live timelines from the on-disk cache. FIFA lag
        # can briefly return an empty/null timeline for a played match; caching
        # that would pin the match to zero events forever. Fetching with
        # use_cache=False (combined with get_timeline not caching empty bodies)
        # ensures a briefly-empty match reloads its real events on a later run.
        timeline = client.get_timeline(
            season=season,
            stage=stage,
            match=match_id,
            competition=competition,
            use_cache=False,
        )
        events = timeline.get("Event") or []
        coords = _match_coords(events)
        for idx, event in enumerate(events):
            rows.append((match_id, idx, enrich_event(event, coords)))
        time.sleep(THROTTLE_SECONDS)

    n = replace_fifa_events(con, rows, loaded_at)
    logger.info("raw.fifa_events: %d rows", n)
    return n


def load_topscorers(
    con: duckdb.DuckDBPyConnection,
    client: FIFAClient,
    loaded_at: datetime,
    season: int = WC_SEASON,
) -> int:
    """Fetch and land the season top scorers (empty-safe)."""
    response = client.get_topscorers(season=season, use_cache=False)
    players = (response or {}).get("PlayerStatsList") or []
    n = replace_fifa_topscorers(con, players, loaded_at)
    logger.info("raw.fifa_topscorers: %d rows", n)
    return n


def _test_2022_final(
    con: duckdb.DuckDBPyConnection, client: FIFAClient, loaded_at: datetime
) -> None:
    """Verification path: land the known-good 2022 final timeline + scorers.

    Lands the single 2022-final match into raw.fifa_matches (synthesized minimal
    calendar row) and its real enriched events into raw.fifa_events, plus the
    2022 season top scorers, so staging can be exercised against real shot data.
    """
    cfg = TEST_2022_FINAL
    logger.info("TEST MODE: landing 2022 final (match=%s)", cfg["match"])
    match_row = {
        "IdMatch": cfg["match"],
        "IdStage": cfg["stage"],
        "IdSeason": cfg["season"],
        "IdCompetition": WC_COMPETITION,
        "MatchStatus": 0,
        "Date": "2022-12-18T15:00:00Z",
    }
    replace_fifa_matches(con, [match_row], loaded_at)
    logger.info("raw.fifa_matches: 1 row (synthetic 2022 final)")
    load_events(con, client, [match_row], loaded_at, season=cfg["season"])
    load_topscorers(con, client, loaded_at, season=cfg["season"])


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(UTC)
    logger.info("loading FIFA raw data into %s", db)
    client = FIFAClient()
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        if os.environ.get("FIFA_TEST_2022_FINAL"):
            _test_2022_final(con, client, loaded_at)
        else:
            matches = load_calendar(con, client, loaded_at)
            load_events(con, client, matches, loaded_at)
            load_topscorers(con, client, loaded_at)
        counts = {
            t: con.execute(f"select count(*) from raw.{t}").fetchone()[0]
            for t in ("fifa_matches", "fifa_events", "fifa_topscorers")
        }
        logger.info("row counts: %s", counts)
    finally:
        con.close()


if __name__ == "__main__":
    main()
