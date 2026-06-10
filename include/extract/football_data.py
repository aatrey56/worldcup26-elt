"""football-data.org (v4) client: the ACTIVE live source for World Cup 2026.

We swapped to this because API-Football's free tier is capped at seasons
2022-2024. football-data.org's free tier covers the World Cup (competition code
WC) at 10 calls/min. Auth is a single header, X-Auth-Token.

Mechanics (session, caching, retry-with-backoff, the get wrapper) live in
BaseApiClient. This subclass overrides only the provider-specific hooks: the
auth header, the cache prefix, the rate-limit header it reads, and how it
detects errors. football-data.org returns proper HTTP error codes (403
restricted, 429 rate-limited) with a JSON {message, errorCode} body, so we
surface that message on failure. 429 and 5xx are retried with backoff; genuine
4xx fail fast.

Run the probe (confirms token + WC 2026 coverage + response shape):
    python -m include.extract.football_data
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from include.extract.base_client import (
    RAW_DIR,
    ApiClientError,
    BaseApiClient,
    TransientApiError,
    is_transient_status,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("football_data")


class FootballDataError(ApiClientError):
    """Raised when football-data.org returns a non-retryable error response."""


class FootballDataClient(BaseApiClient):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        key = api_key or os.environ.get("FOOTBALL_DATA_KEY", "")
        if not key:
            raise FootballDataError(
                "FOOTBALL_DATA_KEY is not set. Register at "
                "football-data.org/client/register and add it to .env."
            )
        resolved_base = (
            base_url
            or os.environ.get("FOOTBALL_DATA_BASE_URL", "https://api.football-data.org/v4")
        )
        # Last seen value of X-Requests-Available-Minute, so callers can throttle
        # against the free-tier 10 calls/min limit. None until the first call.
        self.requests_remaining: int | None = None
        super().__init__(key, resolved_base, logger, cache_dir=cache_dir)

    # --- provider-specific hooks ----------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        return {"X-Auth-Token": self.api_key}

    def _cache_prefix(self) -> str:
        return "fd_"

    def _read_rate_limit(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("X-Requests-Available-Minute")
        if remaining is not None:
            self.logger.info("rate limit: %s calls remaining this minute", remaining)
            try:
                self.requests_remaining = int(remaining)
            except ValueError:
                self.requests_remaining = None

    def _check_response(self, endpoint: str, resp: requests.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message", resp.text)
            except ValueError:
                message = resp.text
            detail = f"{resp.status_code} for {endpoint}: {message}"
            if is_transient_status(resp.status_code):
                raise TransientApiError(detail)
            raise FootballDataError(detail)
        return resp.json()

    # --- typed convenience wrappers -------------------------------------------
    def get_competition(self, code: str = "WC") -> dict[str, Any]:
        return self.get(f"competitions/{code}", {}, use_cache=False)

    def get_matches(
        self, code: str = "WC", season: int = 2026, use_cache: bool = True
    ) -> dict[str, Any]:
        return self.get(f"competitions/{code}/matches", {"season": season}, use_cache=use_cache)

    def get_standings(
        self, code: str = "WC", season: int = 2026, use_cache: bool = True
    ) -> dict[str, Any]:
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
