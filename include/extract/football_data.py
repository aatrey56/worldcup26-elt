"""football-data.org (v4) client: the ACTIVE live source for World Cup 2026.

We swapped to this because API-Football's free tier is capped at seasons
2022-2024. football-data.org's free tier covers the World Cup (competition code
WC) at 10 calls/min. Auth is a single header, X-Auth-Token.

Same design as the API-Football client: retry, rate-limit logging, and on-disk
caching of every raw response so dev re-runs cost zero calls. football-data.org
returns proper HTTP error codes (403 restricted, 429 rate-limited) with a JSON
{message, errorCode} body, so we surface that message on failure.

Run the probe (confirms token + WC 2026 coverage + response shape):
    python -m include.extract.football_data
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("football_data")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "include" / "data" / "raw"


class FootballDataError(RuntimeError):
    """Raised when football-data.org returns an error response."""


class FootballDataClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_KEY", "")
        if not self.api_key:
            raise FootballDataError(
                "FOOTBALL_DATA_KEY is not set. Register at "
                "football-data.org/client/register and add it to .env."
            )
        self.base_url = (
            base_url
            or os.environ.get("FOOTBALL_DATA_BASE_URL", "https://api.football-data.org/v4")
        ).rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": self.api_key})
        # Last seen value of X-Requests-Available-Minute, so callers can throttle
        # against the free-tier 10 calls/min limit. None until the first call.
        self.requests_remaining: int | None = None

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        slug = endpoint.strip("/").replace("/", "_")
        suffix = "_".join(f"{k}-{v}" for k, v in sorted(params.items())) if params else "all"
        return self.cache_dir / f"fd_{slug}__{suffix}.json"

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        remaining = resp.headers.get("X-Requests-Available-Minute")
        if remaining is not None:
            logger.info("rate limit: %s calls remaining this minute", remaining)
            try:
                self.requests_remaining = int(remaining)
            except ValueError:
                self.requests_remaining = None
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message", resp.text)
            except ValueError:
                message = resp.text
            raise FootballDataError(
                f"{resp.status_code} for {endpoint}: {message}"
            )
        return resp.json()

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None, use_cache: bool = True
    ) -> dict[str, Any]:
        params = params or {}
        cache_path = self._cache_path(endpoint, params)
        if use_cache and cache_path.exists():
            logger.info("cache hit: %s", cache_path.name)
            with cache_path.open() as fh:
                return json.load(fh)
        logger.info("GET %s params=%s", endpoint, params)
        payload = self._request(endpoint, params)
        with cache_path.open("w") as fh:
            json.dump(payload, fh, indent=2)
        return payload

    # --- typed convenience wrappers -------------------------------------------
    def get_competition(self, code: str = "WC") -> dict[str, Any]:
        return self.get(f"competitions/{code}", {}, use_cache=False)

    def get_matches(self, code: str = "WC", season: int = 2026, use_cache: bool = True) -> dict[str, Any]:
        return self.get(f"competitions/{code}/matches", {"season": season}, use_cache=use_cache)

    def get_standings(self, code: str = "WC", season: int = 2026, use_cache: bool = True) -> dict[str, Any]:
        return self.get(f"competitions/{code}/standings", {"season": season}, use_cache=use_cache)


def _probe() -> None:
    """Confirm the token works, that WC 2026 is covered, and reveal the shape."""
    code = os.environ.get("WC_COMPETITION", "WC")
    season = int(os.environ.get("WC_SEASON", "2026"))
    client = FootballDataClient()

    logger.info("--- /competitions/%s (coverage + current season) ---", code)
    comp = client.get_competition(code)
    cur = comp.get("currentSeason", {})
    logger.info("competition: %s", comp.get("name"))
    logger.info(
        "currentSeason: %s start=%s end=%s",
        cur.get("startDate"),
        cur.get("startDate"),
        cur.get("endDate"),
    )

    logger.info("--- /competitions/%s/matches season=%s (shape) ---", code, season)
    matches = client.get_matches(code, season, use_cache=False)
    count = matches.get("count") or len(matches.get("matches", []))
    logger.info("matches returned: %s", count)
    if matches.get("matches"):
        m = matches["matches"][0]
        logger.info("top-level keys of a match object: %s", sorted(m.keys()))
        logger.info(
            "sample: %s vs %s | status=%s stage=%s group=%s utcDate=%s",
            m.get("homeTeam", {}).get("name"),
            m.get("awayTeam", {}).get("name"),
            m.get("status"),
            m.get("stage"),
            m.get("group"),
            m.get("utcDate"),
        )
        logger.info("sample score block: %s", m.get("score"))
    else:
        logger.warning("0 matches. Check that WC 2026 is loaded on the free tier yet.")


if __name__ == "__main__":
    _probe()
