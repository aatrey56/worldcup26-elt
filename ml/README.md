# xG (expected goals) model

An interpretable expected-goals model trained **offline** on the FIFA 2022 World
Cup (Qatar) shot corpus and deployed as a **pure-SQL** scorer inside dbt.

## Why this exists

Every shot in the pipeline gets an xG: the probability the shot becomes a goal,
given where it was taken from. Summed per player/team and compared with actual
goals it yields a finishing (over/under-performance) metric and an xG leaderboard.

## Model

Two cases, both trivially expressible in SQL:

**Open-play shots** — logistic regression on two geometric features:

```
xg = 1 / (1 + exp(-(intercept + distance_coef * shot_distance + angle_coef * shot_angle)))
```

* `shot_distance` — Euclidean distance from the shot to the goal centre `(1, 0.5)`
  in the normalized 0-1 pitch frame (attacked goal at `x=1`).
* `shot_angle` — angle (radians) subtended by the 7.32m goal mouth at the shot
  location (the standard xG geometry angle; wider/straighter = larger).

Both features are monotonic and interpretable: closer (smaller distance) and a
wider sight of goal (larger angle) raise xG. We deliberately keep the feature set
to these two terms (no interaction / quadratic term): the two-feature model is
already well calibrated on this corpus, and a minimal model keeps the SQL scorer
simple and robust.

**Penalties** — a single empirical constant `penalty_xg`, the conversion rate of
in-match penalties in the corpus. Penalty geometry is degenerate (every penalty
is the same spot-kick), so a learned function of distance/angle is meaningless;
the empirical rate is the honest xG for a penalty.

## Geometry: train == serve

The training corpus is built by reusing `include.extract.load_fifa.enrich_event`
— the **exact** function the live loader uses at ingest — so `shot_distance`,
`shot_angle`, `is_penalty`, and `is_goal` are computed identically offline and at
serve time. There is no second, drifting implementation of the geometry. Shootout
kicks (Period 11) and own goals are excluded by `enrich_event`'s flags, matching
the Phase 1 rules. Open-play shots with null coordinates are excluded from
training (no geometry); penalties are kept regardless.

## Training data

* Competition 17, season 255711 (FIFA World Cup Qatar 2022), all 64 matches.
* Fetched via `FIFAClient` (calendar + per-match timelines, cached on disk, the
  client throttles between live calls).
* **1443** scored shots: **1009** open-play (trainable), **23** in-match
  penalties, **411** open-play shots dropped for null coordinates.
* **170** goals (153 open-play, 17 penalties).

## Performance (FIFA WC 2022)

| Metric | Value |
| --- | --- |
| Calibration (total predicted xG vs actual goals) | **170.02 vs 170** (ratio 1.000) |
| Open-play calibration (predicted xG vs open-play goals) | 153.02 vs 153 |
| Brier score (open-play, lower is better) | **0.1160** |
| ROC-AUC (open-play) | **0.7357** |
| Penalty conversion rate (`penalty_xg`) | 0.7391 (17/23) |

Reliability (open-play, mean predicted xG vs observed goal rate per bin):

| Predicted-xG bin | n | mean predicted | observed |
| --- | --- | --- | --- |
| [0.00, 0.20) | 700 | 0.088 | 0.099 |
| [0.20, 0.40) | 282 | 0.280 | 0.245 |
| [0.40, 0.60) | 25 | 0.457 | 0.520 |
| [0.60, 0.80) | 2 | 0.627 | 1.000 |

Sanity checks (pass): a close central shot (d=0.21, a=0.50, xG=0.249) >> a
tight-angle far shot (d=0.74, a=0.05, xG=0.013); a six-yard central shot
(d=0.06, a=0.80, xG=0.470) > the penalty-spot-distance central shot.

## Fitted coefficients

Exported to `dbt/seeds/xg_model.csv` (`param,value` rows): `intercept`,
`distance_coef`, `angle_coef`, `penalty_xg`. The dbt model `fct_shot` cross-joins
this seed and applies the logistic formula in pure SQL.

```
intercept      = -0.0817277562
distance_coef  = -5.7877329879
angle_coef     =  0.3859993397
penalty_xg     =  0.7391304348
```

## scikit-learn is DEV-ONLY

`scikit-learn` is used **only** by `ml/train_xg.py` to fit the coefficients. It is
**NOT** a pipeline dependency: scoring happens in pure SQL inside dbt from the
seed, so sklearn is intentionally **not** in the pipeline `requirements.txt` or
the `Dockerfile`. Pinned dev deps live in `ml/requirements.txt`.

## (Re)train

```bash
.venv/bin/pip install -r ml/requirements.txt    # dev venv only
.venv/bin/python -m ml.train_xg                  # rewrites dbt/seeds/xg_model.csv
```

Then `dbt seed` + `dbt build` to flow the new coefficients through `fct_shot`.

## Live 2026 caveat

The coordinate frame for **live** 2026 data is unconfirmed (the metric branch in
`normalize_xy` is verify-on-first-match; see `include/extract/fifa.py`). The model
is trained on the verified 2022 normalized frame. Confirm the live frame on the
first real 2026 match before trusting live xG; if the frame differs, the geometry
(and therefore xG) must be re-validated.
