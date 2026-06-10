"""FIFA public data API (api.fifa.com v3) client: shot-level event source.

This is the free, undocumented FIFA Data API. There is NO key, but it is
unofficial, so we build defensively: a browser-ish User-Agent, a tenacity retry
that backs off on transient/5xx/network failures, an on-disk JSON cache of every
raw response (so dev re-runs cost zero calls), and schema-tolerant parsing that
degrades to nulls rather than throwing.

Mechanics (session, caching, retry, the get wrapper) are reused from
BaseApiClient. This subclass overrides only the provider-specific hooks: the
"auth" header (just the UA, since there is no key), the cache prefix, and how it
detects errors. FIFA returns proper HTTP codes; 429 and 5xx are retried with
backoff, genuine 4xx fail fast. A small polite delay between live calls is the
caller's responsibility (the loader sleeps).

Endpoints (verified by direct probes):
    GET /calendar/matches?idCompetition=17&idSeason=285023&count=300&language=en
    GET /timelines/17/{IdSeason}/{IdStage}/{IdMatch}?language=en
    GET /topseasonplayerstatistics/season/{IdSeason}/topscorers?language=en

COORDINATE FRAME AND NORMALIZATION (see normalize_xy). Probing the 2022 final
revealed the FIFA timeline frame is CENTERED, not 0-1:
  * X is signed and spans about [-1, 1]: the pitch centre is X=0 and each goal
    sits at |X|=1. The sign encodes which goal the action attacks (penalties land
    at |X|=0.790, the penalty spot: 11m from a goal line on a 105m pitch is
    (52.5-11)/52.5 = 0.79). So |X| is the normalized distance from the centre
    toward the attacked goal.
  * Y is signed and spans about [-0.5, 0.5], centre Y=0 (penalties have Y=0.0).
Older data (2022) is already in this normalized centred frame; newer data (2025+)
is in metric pitch units (X ~ +/-52, Y ~ +/-34 centred, or 0-105 / 0-68
corner-origin). We detect the scale per match ROBUSTLY (a high percentile of
absolute coordinates, ignoring stray outliers, must exceed 1.5 for metric; one
glitched value cannot rescale the whole match) and then detect the metric FRAME
(any negative coordinate => centred metric; all non-negative => corner-origin)
before mapping to a single 0-1 frame where the attacked goal is at x=1, y=0.5.
VERIFY-ON-FIRST-MATCH: the metric branches are UNVERIFIED against live data and
emit a one-time WARNING; confirm them on the first real live 2026 match.
    x_norm = |X|              (distance from centre toward goal, 0=centre 1=goal)
    y_norm = Y + 0.5          (centre line -> 0.5)

Run the probe (confirms reachability + WC 2026 + a known-good 2022 timeline):
    python -m include.extract.fifa
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
logger = logging.getLogger("fifa")

# WC 2026 identifiers (verified). Defaults so callers can stay terse.
WC_COMPETITION = 17
WC_SEASON = 285023

# Browser-ish UA: the undocumented API rejects the default python-requests UA.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Metric-pitch dimensions (FIFA standard) used to rescale metric coordinates to
# the centred normalized frame.
#   * CENTRED metric (X in +/-52.5, Y in +/-34): divide by the HALF dimensions.
#   * CORNER-ORIGIN metric (X in 0-105, Y in 0-68): divide by the FULL
#     dimensions; the resulting [0,1]x[0,1] frame is then mapped the same way.
# A coordinate magnitude above METRIC_THRESHOLD means the feed is metric rather
# than already-normalized.
PITCH_HALF_LENGTH_M = 52.5
PITCH_HALF_WIDTH_M = 34.0
PITCH_FULL_LENGTH_M = 105.0
PITCH_FULL_WIDTH_M = 68.0
METRIC_THRESHOLD = 1.5

# Robust scale detection (F2): a single stray coordinate must not flip the whole
# match to the metric branch. Instead of the raw max we use the MEDIAN of all
# absolute coordinates; the feed is metric only if the median exceeds
# METRIC_THRESHOLD. The median is maximally outlier-robust (tolerates up to ~50%
# bad values) yet cleanly separates the two regimes: a normalized match centres
# its magnitudes around ~0.3-0.5 (median well below 1.5 even with several stray
# large values), while a genuinely metric match has a median in the tens. This
# avoids both failure modes of a raw max/high percentile (one glitch flipping a
# normalized match) and of an absolute outlier cap (discarding every coordinate
# in a real metric match, where all values are large).
SCALE_PERCENTILE = 0.5

# Flag flipped to True the first time the metric branch is taken in a process so
# the UNVERIFIED warning (F3) is emitted once, loudly, rather than per event.
_metric_warned = False


class FifaApiError(ApiClientError):
    """Raised when the FIFA API returns a non-retryable error response."""


def _match_scale_is_metric(
    all_match_coords: list[tuple[float | None, float | None]],
) -> bool:
    """Robustly decide whether a match's coordinates are in metric units (F2).

    The verified 2022 frame is already-normalized centred (|coord| <= ~1). A
    single stray reading (e.g. a glitched 50.0 in an otherwise normalized match)
    must NOT rescale every coordinate, so instead of the raw max we take the
    MEDIAN (SCALE_PERCENTILE=0.5) of all absolute coordinates and call the feed
    metric only if the median exceeds METRIC_THRESHOLD. The median is maximally
    outlier-robust: a normalized match with several stray large values keeps a
    median well below 1.5 and stays on the normalized branch, while a genuinely
    metric match (bulk values in the tens) has a large median and is correctly
    detected.
    """
    mags = [abs(c) for pair in all_match_coords for c in pair if c is not None]
    if not mags:
        return False
    mags.sort()
    # Nearest-rank percentile; index clamped into range.
    idx = min(int(SCALE_PERCENTILE * len(mags)), len(mags) - 1)
    return mags[idx] > METRIC_THRESHOLD


def _has_negative_coord(
    all_match_coords: list[tuple[float | None, float | None]],
) -> bool:
    """True if any coordinate in the match is negative (centred metric frame)."""
    return any(
        c is not None and c < 0.0 for pair in all_match_coords for c in pair
    )


def normalize_xy(
    x: float | None,
    y: float | None,
    all_match_coords: list[tuple[float | None, float | None]],
) -> tuple[float | None, float | None]:
    """Normalize a (PositionX, PositionY) pair to a single 0-1 pitch frame.

    The VERIFIED (2022) raw FIFA frame is centred (see module docstring): X in
    [-1, 1] with the attacked goal at |X|=1, Y in [-0.5, 0.5] with the centre at
    0. We:
      1. Detect scale per match robustly (see _match_scale_is_metric): one stray
         coordinate cannot flip the whole match to the metric branch.
      2. If metric, detect the metric FRAME (F3) and recover the centred frame
         (X in [-1,1] with goal at |X|=1, Y in [-0.5,0.5] centred at 0):
           * centred metric (any negative coord; X ~ +/-52.5, Y ~ +/-34):
             divide by the HALF dimensions.
           * corner-origin metric (all non-negative, max > 1.5; X 0-105,
             Y 0-68): map X to [-1,1] via (x/52.5 - 1) so each goal line lands at
             |X|=1 and the halfway line at 0, and Y to [-0.5,0.5] via
             (y/68 - 0.5), matching the centred frame before the common map.
      3. Map the centred frame to a 0-1 frame where the attacked goal is at
         x=1, y=0.5: x_norm = |X| (centre 0, goal 1) and y_norm = Y + 0.5.
    Final values are clamped to [0, 1] so a stray out-of-bounds reading cannot
    poison downstream geometry. Returns (None, None) for a missing coordinate so
    staging gets a clean null.

    VERIFY-ON-FIRST-MATCH (F3): the metric branches below are UNVERIFIED against
    live data. The 2025+ feed is believed to be corner-origin metric, but this
    has not been checked against a real live 2026 match. When the metric branch
    is taken we emit a one-time WARNING; the first live 2026 match MUST be
    inspected to confirm the frame and rescaling before these values are trusted.
    """
    if x is None or y is None:
        return (None, None)

    if _match_scale_is_metric(all_match_coords):
        global _metric_warned
        centred_metric = _has_negative_coord(all_match_coords)
        if not _metric_warned:
            logger.warning(
                "normalize_xy took the UNVERIFIED metric branch "
                "(frame=%s). This path has NOT been verified against live "
                "2026 data: inspect the first live 2026 match to confirm the "
                "coordinate frame and rescaling before trusting x_norm/y_norm.",
                "centred" if centred_metric else "corner-origin",
            )
            _metric_warned = True
        if centred_metric:
            cx_centered = x / PITCH_HALF_LENGTH_M
            cy_centered = y / PITCH_HALF_WIDTH_M
        else:
            # Corner-origin (0-105 / 0-68): map to the centred [-1,1] / [-0.5,0.5]
            # frame so each goal line lands at |X|=1 (X = x/52.5 - 1) and the
            # touchline-centred Y at +/-0.5 (Y = y/68 - 0.5).
            cx_centered = (x / PITCH_HALF_LENGTH_M) - 1.0
            cy_centered = (y / PITCH_FULL_WIDTH_M) - 0.5
    else:
        cx_centered = x
        cy_centered = y

    nx = abs(cx_centered)
    ny = cy_centered + 0.5

    nx = min(max(nx, 0.0), 1.0)
    ny = min(max(ny, 0.0), 1.0)
    return (nx, ny)


class FIFAClient(BaseApiClient):
    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: Path = RAW_DIR,
    ) -> None:
        resolved_base = base_url or os.environ.get("FIFA_BASE_URL", "https://api.fifa.com/api/v3")
        # No key: BaseApiClient still wants one, so we pass an empty string.
        super().__init__("", resolved_base, logger, cache_dir=cache_dir)

    # --- provider-specific hooks ----------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        # No API key. Send a browser UA so the undocumented endpoint responds.
        return {"User-Agent": BROWSER_UA, "Accept": "application/json"}

    def _cache_prefix(self) -> str:
        return "fifa_"

    def _check_response(self, endpoint: str, resp: requests.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            detail = f"{resp.status_code} for {endpoint}: {resp.text[:200]}"
            if is_transient_status(resp.status_code):
                raise TransientApiError(detail)
            raise FifaApiError(detail)
        try:
            return resp.json()
        except ValueError as exc:
            raise FifaApiError(f"non-JSON body for {endpoint}: {resp.text[:200]}") from exc

    # --- typed convenience wrappers -------------------------------------------
    def get_calendar(
        self,
        competition: int = WC_COMPETITION,
        season: int = WC_SEASON,
        count: int = 300,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """All matches for a competition/season. Shape: {"Results": [...]}."""
        return self.get(
            "calendar/matches",
            {
                "idCompetition": competition,
                "idSeason": season,
                "count": count,
                "language": "en",
            },
            use_cache=use_cache,
        )

    def get_timeline(
        self,
        season: int,
        stage: int,
        match: int,
        competition: int = WC_COMPETITION,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Event timeline for one match. Shape: {"Event": [...]}.

        Path order is /timelines/{competition}/{season}/{stage}/{match}.

        NEGATIVE-CACHING GUARD (F8): an empty/null timeline for a played match is
        usually transient FIFA lag, not the truth. We must never serve or persist
        such a body, or the match would be pinned to zero events forever. So when
        the fetched timeline has no events we delete any cache file written for it
        (the base get() writes every response) so a later run re-fetches and
        loads the match's real events. The loader additionally calls this with
        use_cache=False for played/live matches.
        """
        endpoint = f"timelines/{competition}/{season}/{stage}/{match}"
        params = {"language": "en"}
        payload = self.get(endpoint, params, use_cache=use_cache)
        events = (payload or {}).get("Event") if isinstance(payload, dict) else None
        if not events:
            cache_path = self._cache_path(endpoint, params)
            if cache_path.exists():
                logger.warning(
                    "empty/null timeline for match %s; not caching it "
                    "(removing %s) so a later run can reload its events",
                    match,
                    cache_path.name,
                )
                cache_path.unlink()
        return payload

    def get_topscorers(
        self,
        season: int = WC_SEASON,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Top scorers for a season. Shape: likely {"Results": [...]}."""
        return self.get(
            f"topseasonplayerstatistics/season/{season}/topscorers",
            {"language": "en"},
            use_cache=use_cache,
        )


def _first_description(localized: Any) -> str | None:
    """Pull Description from a FIFA localized list like [{"Description": "..."}]."""
    if isinstance(localized, list) and localized:
        first = localized[0]
        if isinstance(first, dict):
            return first.get("Description")
    return None


def _probe() -> None:
    """Confirm reachability: WC 2026 calendar + the known-good 2022 timeline."""
    client = FIFAClient()

    logger.info("--- WC 2026 calendar (competition=%s season=%s) ---", WC_COMPETITION, WC_SEASON)
    calendar = client.get_calendar(use_cache=False)
    results = calendar.get("Results", []) or []
    logger.info("calendar matches: %d", len(results))
    finished = [m for m in results if m.get("MatchStatus") == 0]
    logger.info("finished matches (MatchStatus=0): %d", len(finished))

    logger.info("--- known-good 2022 final timeline (real shots) ---")
    timeline = client.get_timeline(season=255711, stage=285077, match=400128145, use_cache=False)
    events = timeline.get("Event", []) or []
    with_coords = [e for e in events if e.get("PositionX") is not None]
    logger.info("2022 final events: %d (%d with coordinates)", len(events), len(with_coords))
    descs: dict[str, int] = {}
    for ev in with_coords:
        desc = _first_description(ev.get("TypeLocalized")) or "?"
        descs[desc] = descs.get(desc, 0) + 1
    logger.info("coordinate-bearing event descriptions: %s", descs)


if __name__ == "__main__":
    _probe()
