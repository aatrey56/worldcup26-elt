"""Train the World Cup xG (expected goals) model OFFLINE on FIFA 2022 shots.

This is a DEV-ONLY training script. It fits an interpretable expected-goals model
on the FIFA 2022 World Cup (Qatar) shot corpus and exports the fitted parameters
to a dbt SEED (dbt/seeds/xg_model.csv). The pipeline NEVER imports scikit-learn:
the model is scored in pure SQL inside dbt by reading those seed coefficients, so
train-time and serve-time are decoupled. See ml/README.md.

WHY THIS DESIGN
  * Train and serve share IDENTICAL geometry. The training corpus is built by
    reusing include.extract.load_fifa.enrich_event (the exact function the live
    loader uses), so shot_distance / shot_angle / is_penalty / is_goal are
    computed the same way offline as they are at ingest. There is no second,
    drifting implementation of the geometry.
  * Open-play shots: logistic regression on [shot_distance, shot_angle]. Both
    features are monotonic, interpretable, and trivially SQL-expressible as
    1 / (1 + exp(-(intercept + b_dist*distance + b_angle*angle))). We keep the
    feature set minimal (no interaction/quadratic terms) because the two-feature
    model is already well calibrated on this corpus (see the reported metrics);
    adding terms did not improve calibration enough to justify the complexity and
    a more brittle SQL scorer.
  * Penalties: a single empirical constant (the conversion rate of in-match
    penalties in the corpus). Penalty geometry is degenerate (every penalty is
    the same spot-kick), so a learned function of distance/angle is meaningless;
    the empirical rate is the standard, honest xG for a penalty.

DATA
  * Competition 17, season 255711 (FIFA World Cup Qatar 2022).
  * Calendar fetched via FIFAClient, then each match timeline (cached on disk; the
    client throttles between live calls). enrich_event already excludes
    penalty-shootout kicks (Period 11) and own goals from the shot flags, matching
    Phase 1 rules. Open-play shots with null coordinates are excluded from
    training (no geometry); penalties are kept regardless of coordinates.

USAGE (with the repo venv, after installing ml/requirements.txt into it):
    .venv/bin/python -m ml.train_xg
"""

from __future__ import annotations

import csv
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from include.extract.fifa import FIFAClient
from include.extract.load_fifa import (
    THROTTLE_SECONDS,
    _coerce_int,
    _match_coords,
    enrich_event,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_xg")

# FIFA World Cup Qatar 2022 identifiers (verified).
WC2022_COMPETITION = 17
WC2022_SEASON = 255711

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "dbt" / "seeds" / "xg_model.csv"

# Number of bins for the reliability (calibration) check.
RELIABILITY_BINS = 5


@dataclass(frozen=True)
class Shot:
    """A single training shot with the geometry the SQL scorer also sees."""

    distance: float | None
    angle: float | None
    is_penalty: bool
    is_goal: bool


def fetch_2022_shots(
    client: FIFAClient,
    competition: int = WC2022_COMPETITION,
    season: int = WC2022_SEASON,
) -> list[Shot]:
    """Build the 2022 World Cup shot corpus via the live (cached) FIFA feed.

    Fetches the season calendar, then each match timeline (throttled; cached on
    disk so re-runs cost zero calls), and reuses enrich_event so the geometry is
    IDENTICAL to the serving path. Returns one Shot per shot event. Shootout kicks
    and own goals are already excluded by enrich_event's flags.
    """
    calendar = client.get_calendar(competition=competition, season=season)
    matches = calendar.get("Results") or []
    logger.info("2022 calendar: %d matches", len(matches))

    shots: list[Shot] = []
    fetched = 0
    for match in matches:
        match_id = _coerce_int(match.get("IdMatch"))
        stage = _coerce_int(match.get("IdStage"))
        if match_id is None or stage is None:
            logger.warning(
                "skipping match with non-int IdMatch=%r IdStage=%r",
                match.get("IdMatch"),
                match.get("IdStage"),
            )
            continue
        cache_path = client._cache_path(  # noqa: SLF001 - reuse the client's cache key
            f"timelines/{competition}/{season}/{stage}/{match_id}",
            {"language": "en"},
        )
        cached = cache_path.exists()
        timeline = client.get_timeline(
            season=season,
            stage=stage,
            match=match_id,
            competition=competition,
            use_cache=True,
        )
        events = timeline.get("Event") or []
        coords = _match_coords(events)
        for event in events:
            enriched = enrich_event(event, coords)
            if not enriched.get("is_shot"):
                continue
            shots.append(
                Shot(
                    distance=enriched.get("shot_distance"),
                    angle=enriched.get("shot_angle"),
                    is_penalty=bool(enriched.get("is_penalty")),
                    is_goal=bool(enriched.get("is_goal")),
                )
            )
        fetched += 1
        # Only sleep when we actually hit the network (cache miss), to stay polite
        # without slowing down a fully-cached re-run.
        if not cached:
            time.sleep(THROTTLE_SECONDS)
    logger.info("collected %d shots from %d matches", len(shots), fetched)
    return shots


def split_shots(
    shots: list[Shot],
) -> tuple[list[Shot], list[Shot], list[Shot]]:
    """Partition shots into (open_play_trainable, penalties, dropped_no_coords).

    Open-play shots with null coordinates are dropped from training (no geometry).
    Penalties are returned separately (scored by the empirical constant).
    """
    open_play: list[Shot] = []
    penalties: list[Shot] = []
    dropped: list[Shot] = []
    for shot in shots:
        if shot.is_penalty:
            penalties.append(shot)
        elif shot.distance is None or shot.angle is None:
            dropped.append(shot)
        else:
            open_play.append(shot)
    return open_play, penalties, dropped


def fit_open_play_model(
    open_play: list[Shot],
) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    """Fit logistic regression on [distance, angle]; return params + arrays.

    Returns (intercept, distance_coef, angle_coef, predicted_xg, actual_goal) so
    the caller can both export the parameters and evaluate calibration on the
    same fitted probabilities.
    """
    features = np.array([[s.distance, s.angle] for s in open_play], dtype=float)
    labels = np.array([1 if s.is_goal else 0 for s in open_play], dtype=int)

    # No regularization penalty so the exported coefficients are the maximum-
    # likelihood fit (the SQL scorer applies them verbatim); liblinear is stable
    # for this small, low-dimensional problem.
    model = LogisticRegression(penalty=None, solver="lbfgs", max_iter=1000)
    model.fit(features, labels)

    intercept = float(model.intercept_[0])
    distance_coef = float(model.coef_[0][0])
    angle_coef = float(model.coef_[0][1])
    predicted = model.predict_proba(features)[:, 1]
    return intercept, distance_coef, angle_coef, predicted, labels


def reliability_table(
    predicted: np.ndarray, actual: np.ndarray, bins: int = RELIABILITY_BINS
) -> list[tuple[float, float, float, int]]:
    """Group shots into predicted-xG bins; return (lo, mean_pred, mean_act, n).

    A well-calibrated model has mean predicted xG close to the observed goal rate
    within each bin.
    """
    rows: list[tuple[float, float, float, int]] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        # Include the right edge in the final bin so xG == 1.0 lands somewhere.
        if i < bins - 1:
            mask = (predicted >= lo) & (predicted < hi)
        else:
            mask = (predicted >= lo) & (predicted <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append((float(lo), float(predicted[mask].mean()), float(actual[mask].mean()), n))
    return rows


def sanity_checks(intercept: float, distance_coef: float, angle_coef: float) -> None:
    """Log monotonicity sanity checks the model must satisfy.

    A central close shot should outscore a tight-angle far shot, and a shot from
    the penalty-spot distance in open play should beat a 30-yard effort.
    """

    def xg(distance: float, angle: float) -> float:
        z = intercept + distance_coef * distance + angle_coef * angle
        return 1.0 / (1.0 + math.exp(-z))

    # Geometry in the normalized 0-1 frame (goal at x=1, y=0.5; see load_fifa).
    # Penalty-spot distance ~0.21 with a wide central angle; 30 yards ~27m on a
    # 105m pitch -> ~0.26 in x, distance ~0.74 from goal, narrow angle.
    close_central = xg(0.21, 0.50)
    far_tight = xg(0.74, 0.05)
    six_yard_central = xg(0.06, 0.80)
    logger.info(
        "SANITY xG: close-central(d=0.21,a=0.50)=%.3f vs far-tight(d=0.74,a=0.05)=%.3f -> %s",
        close_central,
        far_tight,
        "OK" if close_central > far_tight else "FAIL",
    )
    logger.info(
        "SANITY xG: six-yard-central(d=0.06,a=0.80)=%.3f > close-central=%.3f -> %s",
        six_yard_central,
        close_central,
        "OK" if six_yard_central > close_central else "FAIL",
    )


def write_seed(
    intercept: float,
    distance_coef: float,
    angle_coef: float,
    penalty_xg: float,
    seed_path: Path = SEED_PATH,
) -> None:
    """Write the fitted parameters to the dbt seed (param,value rows)."""
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    params: list[tuple[str, float]] = [
        ("intercept", intercept),
        ("distance_coef", distance_coef),
        ("angle_coef", angle_coef),
        ("penalty_xg", penalty_xg),
    ]
    with seed_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["param", "value"])
        for name, value in params:
            # High precision so the SQL scorer reproduces the fitted probability.
            writer.writerow([name, f"{value:.10f}"])
    logger.info("wrote seed %s", seed_path)


def report(
    open_play: list[Shot],
    penalties: list[Shot],
    dropped: list[Shot],
    predicted: np.ndarray,
    labels: np.ndarray,
    penalty_xg: float,
    intercept: float,
    distance_coef: float,
    angle_coef: float,
) -> dict[str, Any]:
    """Log and return the model report (counts, calibration, Brier, AUC)."""
    n_open = len(open_play)
    n_pen = len(penalties)
    n_dropped = len(dropped)
    open_goals = int(labels.sum())
    pen_goals = sum(1 for p in penalties if p.is_goal)

    # Total predicted xG vs actual goals over ALL scored shots (open-play model +
    # penalty constant) is the headline calibration number.
    total_xg = float(predicted.sum()) + penalty_xg * n_pen
    total_goals = open_goals + pen_goals

    brier = float(brier_score_loss(labels, predicted))
    # AUC is undefined if a class is absent; guard defensively.
    has_both_classes = len(set(labels.tolist())) == 2
    auc = float(roc_auc_score(labels, predicted)) if has_both_classes else float("nan")

    logger.info("=== xG MODEL REPORT (FIFA WC 2022) ===")
    logger.info(
        "shots: %d total scored | %d open-play (trainable) | %d penalties "
        "| %d open-play dropped (null coords)",
        n_open + n_pen + n_dropped,
        n_open,
        n_pen,
        n_dropped,
    )
    logger.info("goals: %d open-play, %d penalties, %d total", open_goals, pen_goals, total_goals)
    logger.info(
        "open-play model: xg = 1/(1+exp(-(%.5f + %.5f*distance + %.5f*angle)))",
        intercept,
        distance_coef,
        angle_coef,
    )
    logger.info(
        "penalty_xg (empirical conversion rate): %.5f (%d/%d)", penalty_xg, pen_goals, n_pen
    )
    logger.info(
        "CALIBRATION: total predicted xG = %.2f vs actual goals = %d (ratio %.3f)",
        total_xg,
        total_goals,
        total_xg / total_goals if total_goals else float("nan"),
    )
    logger.info(
        "open-play CALIBRATION: predicted xG = %.2f vs open-play goals = %d",
        float(predicted.sum()),
        open_goals,
    )
    logger.info("Brier score (open-play): %.4f (lower is better)", brier)
    logger.info("ROC-AUC (open-play): %.4f", auc)

    logger.info("RELIABILITY (open-play, predicted-xG bins):")
    for lo, mean_pred, mean_act, n in reliability_table(predicted, labels):
        logger.info(
            "  bin [%.2f, %.2f): n=%-4d mean_pred=%.3f observed=%.3f",
            lo,
            lo + 1.0 / RELIABILITY_BINS,
            n,
            mean_pred,
            mean_act,
        )

    sanity_checks(intercept, distance_coef, angle_coef)
    return {
        "n_open_play": n_open,
        "n_penalties": n_pen,
        "n_dropped": n_dropped,
        "open_goals": open_goals,
        "penalty_goals": pen_goals,
        "total_xg": total_xg,
        "total_goals": total_goals,
        "brier": brier,
        "auc": auc,
        "intercept": intercept,
        "distance_coef": distance_coef,
        "angle_coef": angle_coef,
        "penalty_xg": penalty_xg,
    }


def main() -> None:
    """Fetch the corpus, fit the model, report metrics, and write the seed."""
    client = FIFAClient()
    shots = fetch_2022_shots(client)
    open_play, penalties, dropped = split_shots(shots)

    if not open_play:
        raise RuntimeError("no trainable open-play shots; cannot fit the xG model")

    intercept, distance_coef, angle_coef, predicted, labels = fit_open_play_model(open_play)

    # Empirical penalty conversion rate. Guard against an empty penalty set
    # (would not happen on the 2022 corpus, but stays defensive): fall back to a
    # standard ~0.78 prior so the seed is always writable.
    if penalties:
        penalty_xg = sum(1 for p in penalties if p.is_goal) / len(penalties)
    else:
        logger.warning("no penalties in corpus; using fallback penalty_xg=0.78")
        penalty_xg = 0.78

    report(
        open_play,
        penalties,
        dropped,
        predicted,
        labels,
        penalty_xg,
        intercept,
        distance_coef,
        angle_coef,
    )
    write_seed(intercept, distance_coef, angle_coef, penalty_xg)


if __name__ == "__main__":
    main()
