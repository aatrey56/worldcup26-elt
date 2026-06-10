"""API-Football (api-sports.io, direct) client for World Cup 2026 ingest.

Auth is a single header, x-apisports-key, against https://v3.football.api-sports.io.
Mechanics (session, caching, retry-with-backoff, the get wrapper) live in
BaseApiClient. This subclass overrides only the provider-specific hooks: the
auth header, the cache prefix, the rate-limit headers it reads, and how it
detects errors.

IMPORTANT: API-Football returns HTTP 200 even on logical errors (bad key, quota
hit, unsupported plan). The real status is in the JSON "errors" field, so we
check that too. Transient transport failures (HTTP 429 and >= 500) are retried
with exponential backoff; genuine client errors fail fast.

Run the probe (confirms key + quota + response shape, ~2 calls):
    python -m include.extract.api_football
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
logger = logging.getLogger("api_football")


class ApiFootballError(ApiClientError):
    """Raised when the API responds with a non-retryable error."""


class ApiFootballClient(BaseApiClient):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        key = api_key or os.environ.get("API_FOOTBALL_KEY", "")
        if not key:
            raise ApiFootballError(
                "API_FOOTBALL_KEY is not set. Add it to .env (see .env.example)."
            )
        resolved_base = (
            base_url
            or os.environ.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")
        )
        super().__init__(key, resolved_base, logger, cache_dir=cache_dir)

    # --- provider-specific hooks ----------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def _read_rate_limit(self, resp: requests.Response) -> None:
        # Surface the daily quota so we never burn through 100 calls blind.
        remaining = resp.headers.get("x-ratelimit-requests-remaining")
        limit = resp.headers.get("x-ratelimit-requests-limit")
        if remaining is not None:
            self.logger.info("quota: %s/%s daily requests remaining", remaining, limit)

    def _check_response(self, endpoint: str, resp: requests.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            detail = f"{resp.status_code} for {endpoint}: {resp.text}"
            if is_transient_status(resp.status_code):
                raise TransientApiError(detail)
            raise ApiFootballError(detail)
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            raise ApiFootballError(f"API returned errors for {endpoint}: {errors}")
        return payload

    # --- typed convenience wrappers -------------------------------------------
    def get_status(self) -> dict[str, Any]:
        """Account status: plan, subscription, and requests used/limit."""
        return self.get("status", {}, use_cache=False)

    def get_fixtures(self, league: int, season: int, use_cache: bool = True) -> dict[str, Any]:
        return self.get("fixtures", {"league": league, "season": season}, use_cache=use_cache)

    def get_standings(self, league: int, season: int, use_cache: bool = True) -> dict[str, Any]:
        return self.get("standings", {"league": league, "season": season}, use_cache=use_cache)


def _probe() -> None:
    """Confirm the key works, show quota, and reveal the real response shape."""
    league = int(os.environ.get("WC_LEAGUE_ID", "1"))
    season = int(os.environ.get("WC_SEASON", "2026"))
    client = ApiFootballClient()

    logger.info("--- /status (does the key work, what is the plan/quota) ---")
    status = client.get_status()
    acct = status.get("response", {}).get("account", {})
    sub = status.get("response", {}).get("subscription", {})
    reqs = status.get("response", {}).get("requests", {})
    logger.info("account: %s %s", acct.get("firstname"), acct.get("lastname"))
    logger.info("plan: %s | active: %s", sub.get("plan"), sub.get("active"))
    logger.info("requests today: %s / %s", reqs.get("current"), reqs.get("limit_day"))

    logger.info("--- /fixtures league=%s season=%s (coverage + shape) ---", league, season)
    fixtures = client.get_fixtures(league, season, use_cache=False)
    results = fixtures.get("results", 0)
    logger.info("fixtures returned: %s", results)
    if results:
        sample = fixtures["response"][0]
        logger.info("top-level keys of a fixture object: %s", sorted(sample.keys()))
        logger.info(
            "sample: %s vs %s, status=%s, date=%s",
            sample["teams"]["home"]["name"],
            sample["teams"]["away"]["name"],
            sample["fixture"]["status"]["short"],
            sample["fixture"]["date"],
        )
    else:
        logger.warning(
            "0 fixtures. The free plan may not cover WC 2026, or the league/season is off. "
            "Check the 'errors' field and your plan coverage."
        )


if __name__ == "__main__":
    _probe()
