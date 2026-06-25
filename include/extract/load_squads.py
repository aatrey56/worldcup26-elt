"""Squad-quality loader: land each WC 2026 national-team squad into raw.squads.

Source is the Wikipedia article "2026 FIFA World Cup squads"
(https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads). It carries one HTML
table per team (48 of them), each with columns No. | Pos. | Player | DOB | Caps |
Goals | Club. The team name is NOT inside its table; it is the section heading
(an <h3>) immediately preceding the table, so we associate every squad table with
the nearest preceding <h3> team name. Each table is parsed with pandas.read_html
and the Player / Club / Pos. cells are landed one row per player into:

    raw.squads(team_name VARCHAR, player VARCHAR, club VARCHAR, position VARCHAR,
               payload JSON, loaded_at TIMESTAMP)
        one row per player appearance in a squad. payload keeps the full parsed
        row object so staging can stay a clean 1:1 read. The grain is the
        (team_name, player) pair.

This is a "context" stat feeding fct_squad_quality: how many of a team's players
play club football in a top-5 European league (the dbt seed top5_clubs.csv).

RESILIENCE: squads change rarely, and Wikipedia is a best-effort fallback-style
source, so a fetch/parse failure must NOT abort the live FIFA-driven build. The
loader mirrors load_raw's graceful-degrade pattern: it ensures the raw.squads
shell exists, and on any network/parse error it logs loudly and leaves the table
as-is (empty on a fresh warehouse, prior data on a persistent one) so dbt runs on
the previous snapshot rather than crashing. fct_squad_quality is empty-safe.

The raw response HTML is cached to include/data/raw so dev re-runs cost zero
calls. Run with the project venv:

    python -m include.extract.load_squads
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import duckdb
import requests

from include.extract.raw_tables import RawContractError, replace_squads

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_squads")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "include" / "data" / "warehouse.duckdb"
CACHE_DIR = REPO_ROOT / "include" / "data" / "raw"

SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
CACHE_FILE = "wikipedia_2026_world_cup_squads.html"
# A descriptive User-Agent is polite and avoids Wikipedia's default-UA blocks.
USER_AGENT = "WC2026-ELT/1.0 (squad-quality feature; +https://github.com/aatrey56)"
HTTP_TIMEOUT = 60

# A genuine squad table on the page carries this class; each is preceded by an
# <h3> with the team name. WC 2026 has 48 teams, so we expect 48 such tables.
SQUAD_TABLE_XPATH = "//table[contains(@class, 'plainrowheaders')]"
EXPECTED_TEAMS = 48

# Soft errors that degrade to "keep the previous snapshot" instead of aborting
# the whole build (squads are a rarely-changing context stat, not the live feed).
SQUADS_SOFT_ERRORS = (
    requests.exceptions.RequestException,
    RawContractError,
    ValueError,  # pandas.read_html / lxml parse failures
    ImportError,  # lxml / pandas html parser missing in a stripped env
)


def _db_path() -> str:
    return os.environ.get("DUCKDB_PATH", str(DEFAULT_DB))


def _clean(text: Any) -> str:
    """Collapse whitespace and strip Wikipedia footnote markers from a cell."""
    if text is None:
        return ""
    value = str(text)
    # Drop bracketed footnote markers like [a], [12], [note 1].
    value = re.sub(r"\[[^\]]*\]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    # pandas renders an empty/NaN cell as the literal "nan".
    return "" if value.lower() == "nan" else value


def fetch_html(use_cache: bool = False) -> str:
    """Fetch the squads page HTML, caching the raw response to disk.

    use_cache serves a prior cached copy when present (dev re-runs cost zero
    calls); the live loader fetches fresh so squad updates flow through.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / CACHE_FILE
    if use_cache and cache_path.exists():
        logger.info("cache hit: %s", cache_path.name)
        return cache_path.read_text(encoding="utf-8")
    logger.info("GET %s", SQUADS_URL)
    resp = requests.get(
        SQUADS_URL, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT
    )
    resp.raise_for_status()
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


def parse_squads(html: str) -> list[dict[str, Any]]:
    """Parse the squads page into one dict per player.

    Returns a list of {team_name, player, club, position} dicts. Associates each
    squad table with the nearest preceding <h3> (the team name) and reads the
    Player / Club / Pos. columns via pandas.read_html. Raises RawContractError if
    the page shape is unrecognizable (no squad tables, or a wildly wrong team
    count) so a Wikipedia restructure fails loudly at the boundary instead of
    silently landing an empty/garbage table.
    """
    # Imported lazily so a stripped environment without lxml/pandas surfaces as a
    # soft ImportError the caller degrades on, rather than a hard import-time crash.
    import lxml.html
    import pandas as pd

    doc = lxml.html.fromstring(html)
    tables = doc.xpath(SQUAD_TABLE_XPATH)
    if not tables:
        raise RawContractError(
            "no squad tables found on the Wikipedia squads page (shape changed?)"
        )
    if not (EXPECTED_TEAMS // 2 <= len(tables) <= EXPECTED_TEAMS * 2):
        # Allow some slack (a team table could be split), but a wildly wrong
        # count means the page was restructured; fail loudly.
        raise RawContractError(
            f"expected ~{EXPECTED_TEAMS} squad tables, found {len(tables)}"
        )

    rows: list[dict[str, Any]] = []
    for table in tables:
        heading = table.xpath("preceding::h3[1]")
        team_name = _clean(heading[0].text_content()) if heading else ""
        if not team_name:
            logger.warning("squad table with no preceding team heading, skipping")
            continue
        frame = pd.read_html(StringIO(lxml.html.tostring(table).decode()))[0]
        frame.columns = [str(c) for c in frame.columns]
        if "Player" not in frame.columns or "Club" not in frame.columns:
            logger.warning(
                "squad table for %s missing Player/Club columns (%s), skipping",
                team_name,
                list(frame.columns),
            )
            continue
        for _, record in frame.iterrows():
            player = _clean(record.get("Player"))
            if not player:
                continue
            rows.append(
                {
                    "team_name": team_name,
                    "player": player,
                    "club": _clean(record.get("Club")),
                    "position": _clean(record.get("Pos.")),
                }
            )

    if not rows:
        raise RawContractError("parsed zero squad players (page shape changed?)")
    teams = {r["team_name"] for r in rows}
    logger.info("parsed %d players across %d teams", len(rows), len(teams))
    return rows


def _ensure_raw_squads(con: duckdb.DuckDBPyConnection) -> None:
    """Create the empty raw.squads shell if absent.

    Guarantees staging always has a relation to read, so a failed fetch degrades
    cleanly (empty/previous table) instead of dbt erroring on a missing source.
    """
    con.execute(
        "create table if not exists raw.squads ("
        "team_name varchar, player varchar, club varchar, "
        "position varchar, payload json, loaded_at timestamp)"
    )


def main() -> None:
    db = _db_path()
    loaded_at = datetime.now(UTC)
    logger.info("loading WC 2026 squads into %s", db)
    con = duckdb.connect(db)
    try:
        con.execute("create schema if not exists raw")
        _ensure_raw_squads(con)
        try:
            html = fetch_html(use_cache=False)
            rows = parse_squads(html)
            n = replace_squads(con, rows, loaded_at)
            logger.info("raw.squads: %d rows", n)
        except SQUADS_SOFT_ERRORS as exc:
            # Squads are a rarely-changing context stat, not the live source of
            # truth. A Wikipedia outage / restructure must not abort the live
            # FIFA build: log loudly and keep the previous snapshot (or empty on
            # a fresh warehouse). fct_squad_quality is empty-safe.
            logger.warning(
                "squads load failed (%s: %s); keeping previous snapshot",
                type(exc).__name__,
                exc,
            )
    finally:
        con.close()


if __name__ == "__main__":
    main()
