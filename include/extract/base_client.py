"""Shared mechanics for the football data API clients.

FootballDataClient and ApiFootballClient share almost everything: a requests
Session, an on-disk cache of every raw response (so dev re-runs cost zero calls),
a tenacity retry that backs off on transient failures, and a get() wrapper that
checks the cache before calling _request().

The providers differ only in a few hooks, which subclasses override:

    _auth_header()       the auth header dict to set on the session.
    _cache_prefix()      filename prefix for cached responses.
    _read_rate_limit()   pull and log the provider's rate-limit headers.
    _check_response()    raise on a logical/HTTP error (provider-specific).

Transient failures (HTTP 429 rate-limit and >= 500 server errors) raise a
TransientApiError, which the retry retries with exponential backoff. Genuine
client errors (4xx other than 429) raise the provider's non-retryable error so
they fail fast.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "include" / "data" / "raw"


class ApiClientError(RuntimeError):
    """Base for non-retryable API client errors (e.g. genuine 4xx)."""


class TransientApiError(RuntimeError):
    """Retryable API failure (HTTP 429 rate-limit or >= 500 server error)."""


def is_transient_status(status_code: int) -> bool:
    """True for HTTP status codes worth retrying: 429 and any 5xx."""
    return status_code == 429 or status_code >= 500


class BaseApiClient:
    """Common session, caching, retry, and get-with-caching mechanics.

    Subclasses set provider-specific attributes in __init__ and override the
    hook methods below. They must call super().__init__() with the resolved key,
    base_url, and logger.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        logger: logging.Logger,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self._auth_header())

    # --- provider-specific hooks ----------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        """Return the auth header(s) to set on the session."""
        raise NotImplementedError

    def _cache_prefix(self) -> str:
        """Filename prefix for cached responses (keeps providers separate)."""
        return ""

    def _read_rate_limit(self, resp: requests.Response) -> None:
        """Pull and log the provider's rate-limit headers (best effort)."""

    def _check_response(self, endpoint: str, resp: requests.Response) -> dict[str, Any]:
        """Validate the response and return the parsed JSON payload.

        Must raise TransientApiError for retryable failures (429/5xx) and the
        provider's non-retryable error for genuine client errors.
        """
        raise NotImplementedError

    # --- shared mechanics -----------------------------------------------------
    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        slug = endpoint.strip("/").replace("/", "_")
        suffix = "_".join(f"{k}-{v}" for k, v in sorted(params.items())) if params else "all"
        return self.cache_dir / f"{self._cache_prefix()}{slug}__{suffix}.json"

    @retry(
        retry=retry_if_exception_type(TransientApiError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        self._read_rate_limit(resp)
        return self._check_response(endpoint, resp)

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None, use_cache: bool = True
    ) -> dict[str, Any]:
        """GET an endpoint, caching the raw response to disk."""
        params = params or {}
        cache_path = self._cache_path(endpoint, params)
        if use_cache and cache_path.exists():
            self.logger.info("cache hit: %s", cache_path.name)
            with cache_path.open() as fh:
                return json.load(fh)
        self.logger.info("GET %s params=%s", endpoint, params)
        payload = self._request(endpoint, params)
        with cache_path.open("w") as fh:
            json.dump(payload, fh, indent=2)
        return payload


def env(name: str, default: str = "") -> str:
    """Read an environment variable with a default."""
    return os.environ.get(name, default)
