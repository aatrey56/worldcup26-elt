"""Action-value models: xT (expected threat) and VAEP.

Two complementary on-ball value frameworks, both from socceraction (KU Leuven):

xT (expected threat)
    A grid-based ball-progression model. Each pitch cell has a value equal to the
    long-run probability that possession starting there leads to a goal. A
    move action (pass or carry) is credited the change in cell value it produces.
    Captures only ball progression for successful moves; it ignores defending,
    shooting quality and turnovers. We fit the grid on the tournament's own
    actions (self-contained, reproducible) using a 16x12 grid.

VAEP (Valuing Actions by Estimating Probabilities)
    Frames every action as changing two probabilities over the next ~10 actions:
    P(team scores) and P(team concedes). VAEP value = dP(score) - dP(concede).
    Two gradient-boosted classifiers are trained on SPADL game-states (3 previous
    actions of context). This is the cross-position "common currency": it values
    offensive AND defensive actions (tackles, interceptions, clearances) on the
    same goal-probability scale. Trained on Euro 2024 itself via grouped
    cross-validation so every action is scored out-of-fold (no leakage onto the
    player who produced it from his own future).

Both models operate on SPADL actions produced in ``data.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import socceraction.spadl as spadl
import socceraction.vaep.features as fs
import socceraction.vaep.formula as vaepformula
import socceraction.vaep.labels as lab
from socceraction.xthreat import ExpectedThreat
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

logger = logging.getLogger(__name__)

# xT grid resolution (StatsBomb pitch 105x68, standard socceraction defaults).
XT_GRID_L: int = 16
XT_GRID_W: int = 12

# VAEP feature transformers (the standard socceraction feature set).
_VAEP_FEATURES = [
    fs.actiontype_onehot,
    fs.bodypart_onehot,
    fs.result_onehot,
    fs.startlocation,
    fs.endlocation,
    fs.startpolar,
    fs.endpolar,
    fs.movement,
    fs.team,
    fs.time_delta,
    fs.space_delta,
    fs.goalscore,
]


def _orient_left_to_right(actions: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Reorient every game's actions so each team attacks left-to-right.

    xT's ``fit`` and ``rate`` use raw start_x/end_x and assume the attacking
    direction is increasing x. SPADL keeps both teams in a single coordinate frame
    where the away team attacks right-to-left, so without this step a defender's
    backward clearance looks like forward progress. We apply socceraction's
    ``play_left_to_right`` per game (it mirrors the away team's coordinates).
    """
    home_lookup = games.set_index("game_id")["home_team_id"].to_dict()
    parts: list[pd.DataFrame] = []
    for game_id, ga in actions.groupby("game_id", sort=False):
        ltr = spadl.play_left_to_right(ga.copy(), int(home_lookup[game_id]))
        parts.append(ltr)
    return pd.concat(parts).loc[actions.index]


def compute_xt(actions: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Fit an xT grid on the tournament and rate every move action.

    Actions are first reoriented left-to-right per game so attacking progression
    increases x for both teams (see ``_orient_left_to_right``).

    Args:
        actions: SPADL actions for all games (with names added).
        games: Games frame (for home_team_id per game, used for orientation).

    Returns:
        The actions frame with an added ``xt_value`` column. Non-move actions and
        unsuccessful moves get 0.0.
    """
    logger.info("fitting xT grid (%dx%d) on %d actions", XT_GRID_L, XT_GRID_W, len(actions))
    ltr = _orient_left_to_right(actions, games)
    xt_model = ExpectedThreat(l=XT_GRID_L, w=XT_GRID_W)
    xt_model.fit(ltr)

    # rate() credits the xT delta to successful move actions and returns NaN for
    # non-move / unsuccessful actions; coerce those to 0.
    rated = xt_model.rate(ltr)
    out = actions.copy()
    out["xt_value"] = np.nan_to_num(np.asarray(rated, dtype=float), nan=0.0)
    logger.info("xT total rated value sum=%.2f", float(out["xt_value"].sum()))
    return out


def _build_features(actions: pd.DataFrame, home_team_id: int, nb_prev: int = 3) -> pd.DataFrame:
    """Build the VAEP feature matrix for a single game's actions."""
    gs = fs.gamestates(actions, nb_prev)
    gs = fs.play_left_to_right(gs, home_team_id)
    return pd.concat([f(gs) for f in _VAEP_FEATURES], axis=1)


def compute_vaep(
    actions: pd.DataFrame,
    games: pd.DataFrame,
    n_splits: int = 5,
    random_state: int = 42,
) -> pd.DataFrame:
    """Train VAEP classifiers with grouped CV and value every action out-of-fold.

    Per-game features and labels are built first (labels and play-direction depend
    on game boundaries). Two ``HistGradientBoostingClassifier`` models predict
    P(score) and P(concede). We use GroupKFold by game so a game's actions are
    always scored by a model that never saw that game, avoiding leakage.

    Args:
        actions: SPADL actions for all games.
        games: Games frame (for home_team_id per game).
        n_splits: Number of grouped folds.
        random_state: Seed for the classifiers.

    Returns:
        Actions frame augmented with ``offensive_value``, ``defensive_value`` and
        ``vaep_value`` columns.
    """
    home_lookup = games.set_index("game_id")["home_team_id"].to_dict()

    feat_parts: list[pd.DataFrame] = []
    score_parts: list[pd.DataFrame] = []
    concede_parts: list[pd.DataFrame] = []
    action_parts: list[pd.DataFrame] = []

    logger.info("building VAEP features/labels per game")
    for game_id, game_actions in actions.groupby("game_id", sort=False):
        game_actions = game_actions.sort_values("action_id").reset_index(drop=True)
        home_team_id = int(home_lookup[game_id])
        X = _build_features(game_actions, home_team_id)
        y_scores = lab.scores(game_actions)
        y_concedes = lab.concedes(game_actions)
        X.index = game_actions.index
        feat_parts.append(X)
        score_parts.append(y_scores.set_axis(game_actions.index))
        concede_parts.append(y_concedes.set_axis(game_actions.index))
        action_parts.append(game_actions.assign(_game_id=game_id))

    X_all = pd.concat(feat_parts, ignore_index=True)
    y_scores = pd.concat(score_parts, ignore_index=True)["scores"].astype(int)
    y_concedes = pd.concat(concede_parts, ignore_index=True)["concedes"].astype(int)
    actions_all = pd.concat(action_parts, ignore_index=True)
    groups = actions_all["_game_id"].to_numpy()

    logger.info(
        "training VAEP on %d actions, %d features, %d positives (score)",
        len(X_all),
        X_all.shape[1],
        int(y_scores.sum()),
    )

    p_scores = np.zeros(len(X_all))
    p_concedes = np.zeros(len(X_all))

    gkf = GroupKFold(n_splits=n_splits)
    for fold, (train_idx, test_idx) in enumerate(gkf.split(X_all, y_scores, groups)):
        logger.info("VAEP fold %d/%d", fold + 1, n_splits)
        for target, store in ((y_scores, p_scores), (y_concedes, p_concedes)):
            clf = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.05, random_state=random_state
            )
            clf.fit(X_all.iloc[train_idx], target.iloc[train_idx])
            store[test_idx] = clf.predict_proba(X_all.iloc[test_idx])[:, 1]

    vaep = vaepformula.value(
        actions_all.drop(columns="_game_id"),
        pd.Series(p_scores, index=actions_all.index),
        pd.Series(p_concedes, index=actions_all.index),
    )
    actions_all["offensive_value"] = vaep["offensive_value"].to_numpy()
    actions_all["defensive_value"] = vaep["defensive_value"].to_numpy()
    actions_all["vaep_value"] = vaep["vaep_value"].to_numpy()
    actions_all = actions_all.drop(columns="_game_id")
    logger.info(
        "VAEP done: total vaep_value=%.2f", float(actions_all["vaep_value"].sum())
    )
    return actions_all


def save_xt_model(actions: pd.DataFrame, path: Path) -> None:
    """Fit and persist an xT model (utility, optional)."""
    model = ExpectedThreat(l=XT_GRID_L, w=XT_GRID_W)
    model.fit(actions)
    model.save_model(str(path))
