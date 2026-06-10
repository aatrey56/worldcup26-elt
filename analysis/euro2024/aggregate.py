"""Player-level aggregation, normalization, shrinkage and opponent adjustment.

Takes per-action value (VAEP, xT) plus possession chains and produces tidy
per-player tables ready for ranking:

- Minutes played, position group, primary team.
- Summed VAEP / xT, plus xGChain and xGBuildup from possession chains.
- Opponent-strength weighting of each match's value contribution.
- Per-90 normalization.
- Empirical-Bayes shrinkage of per-90 VAEP toward the position-group mean,
  weighted by minutes, so small samples regress to the prior.

Every modeling choice and its bias is documented inline and in the README.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Map StatsBomb starting positions to coarse position groups used for shrinkage
# priors and the per-position ranking. Goalkeepers are split out entirely.
POSITION_GROUP_MAP: dict[str, str] = {
    "Goalkeeper": "GK",
    "Right Back": "DEF",
    "Left Back": "DEF",
    "Right Center Back": "DEF",
    "Left Center Back": "DEF",
    "Center Back": "DEF",
    "Right Wing Back": "DEF",
    "Left Wing Back": "DEF",
    "Right Defensive Midfield": "MID",
    "Left Defensive Midfield": "MID",
    "Center Defensive Midfield": "MID",
    "Right Center Midfield": "MID",
    "Left Center Midfield": "MID",
    "Center Midfield": "MID",
    "Right Attacking Midfield": "MID",
    "Left Attacking Midfield": "MID",
    "Center Attacking Midfield": "MID",
    "Right Midfield": "MID",
    "Left Midfield": "MID",
    "Right Wing": "FWD",
    "Left Wing": "FWD",
    "Right Center Forward": "FWD",
    "Left Center Forward": "FWD",
    "Center Forward": "FWD",
    "Secondary Striker": "FWD",
}


def player_minutes_and_positions(players: pd.DataFrame) -> pd.DataFrame:
    """Aggregate minutes played and assign each player a primary position group.

    A player's primary team is their most frequent team_id; the primary position
    is the position group in which they accumulated the most minutes (excluding
    the generic "Substitute" label, which carries no positional info).

    Returns one row per player: player_id, player_name, team_id, minutes,
    position_group, primary_position.
    """
    df = players.copy()
    df["position_group"] = df["starting_position_name"].map(POSITION_GROUP_MAP)

    # Total minutes per player.
    minutes = df.groupby("player_id")["minutes_played"].sum().rename("minutes")

    # Primary team: team with most minutes.
    team = (
        df.groupby(["player_id", "team_id"])["minutes_played"].sum()
        .reset_index()
        .sort_values("minutes_played", ascending=False)
        .drop_duplicates("player_id")
        .set_index("player_id")["team_id"]
    )

    # Primary position group: weight by minutes, ignore unmapped Substitute rows.
    posdf = df.dropna(subset=["position_group"])
    pos = (
        posdf.groupby(["player_id", "position_group"])["minutes_played"].sum()
        .reset_index()
        .sort_values("minutes_played", ascending=False)
        .drop_duplicates("player_id")
        .set_index("player_id")["position_group"]
    )
    primary_pos = (
        posdf.groupby(["player_id", "starting_position_name"])["minutes_played"].sum()
        .reset_index()
        .sort_values("minutes_played", ascending=False)
        .drop_duplicates("player_id")
        .set_index("player_id")["starting_position_name"]
    )

    name = df.drop_duplicates("player_id").set_index("player_id")["player_name"]

    out = pd.DataFrame({"minutes": minutes})
    out["player_name"] = name
    out["team_id"] = team
    out["position_group"] = pos
    out["primary_position"] = primary_pos
    out = out.reset_index()
    # Players who only ever appeared as unused/sub with no position get group NaN;
    # drop those with zero minutes, keep others as UNK.
    out["position_group"] = out["position_group"].fillna("UNK")
    return out


def opponent_strength(games: pd.DataFrame) -> pd.DataFrame:
    """Compute a per-team pre/within-tournament strength proxy.

    PROXY CHOICE AND LIMITATION:
        We lack a clean pre-tournament FIFA/Elo seed in the open data, so we use a
        within-tournament proxy: each team's goal difference per game across the
        tournament, converted to a 0..1 strength score via min-max scaling. This
        is circular (a team's results inform its own "strength"), so it is a
        coarse adjustment, not a true ex-ante seed. It still down-weights value
        piled up against weak sides and up-weights value vs strong sides. A team
        that conceded heavily will read as "weak" even if its xG was decent.

    Returns one row per team_id: gd_per_game, strength (0..1).
    """
    rows: list[dict] = []
    for _, g in games.iterrows():
        rows.append({"team_id": g["home_team_id"], "gf": g["home_score"], "ga": g["away_score"]})
        rows.append({"team_id": g["away_team_id"], "gf": g["away_score"], "ga": g["home_score"]})
    tg = pd.DataFrame(rows)
    agg = tg.groupby("team_id").agg(gf=("gf", "sum"), ga=("ga", "sum"), games=("gf", "size"))
    agg["gd_per_game"] = (agg["gf"] - agg["ga"]) / agg["games"]
    lo, hi = agg["gd_per_game"].min(), agg["gd_per_game"].max()
    agg["strength"] = (agg["gd_per_game"] - lo) / (hi - lo) if hi > lo else 0.5
    return agg.reset_index()[["team_id", "gd_per_game", "strength"]]


def opponent_adjusted_vaep(
    actions: pd.DataFrame, games: pd.DataFrame, strength: pd.DataFrame
) -> pd.DataFrame:
    """Sum VAEP per player, weighting each action by the opponent's strength.

    The opponent in a given game is the other team. We multiply each action's VAEP
    by a weight ``0.5 + strength_opponent`` (range ~0.5..1.5) so value generated
    against strong opponents counts more. The 0.5 floor stops the weakest opponent
    contributing zero. We return both raw-summed and opponent-adjusted VAEP.

    Returns per-player: vaep_raw, vaep_adj, off_raw, def_raw.
    """
    strength_map = strength.set_index("team_id")["strength"].to_dict()
    # Build game_id -> (team_id -> opponent_team_id)
    opp: dict[tuple[int, int], int] = {}
    for _, g in games.iterrows():
        opp[(g["game_id"], g["home_team_id"])] = g["away_team_id"]
        opp[(g["game_id"], g["away_team_id"])] = g["home_team_id"]

    a = actions.copy()
    a["opp_team_id"] = [
        opp.get((gid, tid)) for gid, tid in zip(a["game_id"], a["team_id"], strict=True)
    ]
    a["opp_strength"] = a["opp_team_id"].map(strength_map).fillna(0.5)
    a["weight"] = 0.5 + a["opp_strength"]
    a["vaep_adj_contrib"] = a["vaep_value"] * a["weight"]

    g = a.groupby("player_id").agg(
        vaep_raw=("vaep_value", "sum"),
        vaep_adj=("vaep_adj_contrib", "sum"),
        off_raw=("offensive_value", "sum"),
        def_raw=("defensive_value", "sum"),
    )
    return g.reset_index()


def sum_xt(actions: pd.DataFrame) -> pd.DataFrame:
    """Sum xT value per player."""
    return (
        actions.groupby("player_id")["xt_value"].sum().rename("xt").reset_index()
    )


def xg_chain_buildup(
    possession: pd.DataFrame, shots: pd.DataFrame
) -> pd.DataFrame:
    """Compute xGChain and xGBuildup per player from possession involvement.

    xGChain(player) = sum over possessions the player was involved in of the total
    shot xG generated in that possession (a possession can contain multiple shots;
    we sum them). xGBuildup is the same but excludes possessions in which the
    player's only involvement was taking a shot or making the key pass, isolating
    pure build-up contribution.

    Returns per-player: xg_chain, xg_buildup.
    """
    # Total shot xG per (game, possession).
    poss_xg = (
        shots.groupby(["game_id", "possession"])["statsbomb_xg"].sum().rename("poss_xg")
    )
    inv = possession.merge(
        poss_xg, on=["game_id", "possession"], how="left"
    )
    inv["poss_xg"] = inv["poss_xg"].fillna(0.0)

    # xGChain: every involvement counts.
    chain = inv.groupby("player_id")["poss_xg"].sum().rename("xg_chain")

    # xGBuildup: exclude rows where the player's involvement was a shot or key pass.
    buildup_inv = inv[~(inv["took_shot"] | inv["made_key_pass"])]
    buildup = buildup_inv.groupby("player_id")["poss_xg"].sum().rename("xg_buildup")

    out = pd.concat([chain, buildup], axis=1).fillna(0.0).reset_index()
    return out


def per90(value: pd.Series, minutes: pd.Series) -> pd.Series:
    """Normalize a counting value to per-90-minutes. Zero minutes -> 0."""
    return np.where(minutes > 0, value / minutes * 90.0, 0.0)


def shrink_per90(
    df: pd.DataFrame,
    value_col: str,
    minutes_col: str,
    group_col: str,
    prior_strength_minutes: float = 270.0,
) -> pd.Series:
    """Empirical-Bayes shrinkage of a per-90 value toward the position-group mean.

    We treat each player's per-90 value as a noisy estimate whose reliability grows
    with minutes. The shrunk estimate is a minutes-weighted blend of the player's
    own per-90 and the (minutes-weighted) group mean per-90:

        w = minutes / (minutes + prior_strength_minutes)
        shrunk = w * player_per90 + (1 - w) * group_mean_per90

    ``prior_strength_minutes`` (default 270 = three full matches) sets how much
    evidence is needed before a player is trusted over the group prior. Bias: this
    pulls extreme small-sample performers toward the middle, which is the intent
    (it suppresses a 20-minute cameo topping the chart) but slightly penalizes
    genuine standouts who played few minutes.

    Returns the shrunk per-90 series aligned to df's index.
    """
    per90_vals = pd.Series(per90(df[value_col], df[minutes_col]), index=df.index)
    minutes = df[minutes_col]

    # Minutes-weighted group mean per-90 as the prior.
    tmp = pd.DataFrame({"g": df[group_col], "p90": per90_vals, "m": minutes})
    group_mean = (
        tmp.assign(num=tmp["p90"] * tmp["m"])
        .groupby("g")
        .apply(lambda x: x["num"].sum() / x["m"].sum() if x["m"].sum() > 0 else 0.0)
    )
    prior = df[group_col].map(group_mean).astype(float)
    w = minutes / (minutes + prior_strength_minutes)
    return w * per90_vals + (1.0 - w) * prior
