"""API-Football (api-sports.io, direct) client for World Cup 2026 ingest.

Auth is a single header, x-apisports-key, against https://v3.football.api-sports.io.
The client retries transient failures, logs the rate-limit headers, and caches every
raw response to include/data/raw/ so re-runs during development cost zero API calls.

IMPORTANT: API-Football returns HTTP 200 even on logical errors (bad key, quota hit,
unsupported plan). The real status is in the JSON "errors" field, so we check that too.

Run the probe (confirms key + quota + response shape, ~2 calls):
    python -m include.extract.api_football
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
logger = logging.getLogger("api_football")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "include" / "data" / "raw"


class ApiFootballError(RuntimeError):
    """Raised when the API responds with a logical error in the body."""


class ApiFootballClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY", "")
        if not self.api_key:
            raise ApiFootballError(
                "API_FOOTBALL_KEY is not set. Add it to .env (see .env.example)."
            )
        self.base_url = (
            base_url
            or os.environ.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")
        ).rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        slug = endpoint.strip("/").replace("/", "_")
        suffix = "_".join(f"{k}-{v}" for k, v in sorted(params.items())) if params else "all"
        return self.cache_dir / f"{slug}__{suffix}.json"

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        # Surface the daily quota so we never burn through 100 calls blind.
        remaining = resp.headers.get("x-ratelimit-requests-remaining")
        limit = resp.headers.get("x-ratelimit-requests-limit")
        if remaining is not None:
            logger.info("quota: %s/%s daily requests remaining", remaining, limit)
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            raise ApiFootballError(f"API returned errors for {endpoint}: {errors}")
        return payload

    def get(
        self, endpoint: str, params: dict[str, Any], use_cache: bool = True
    ) -> dict[str, Any]:
        """GET an endpoint, caching the raw response to disk."""
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
