"""Assemble the final ranking tables and write CSV deliverables.

Builds, from the aggregated per-player frames:
- overall_value_ranking: opponent-adjusted, shrunk VAEP/90 (outfield only).
- per_position_top: top players by position group on the same metric.
- xt_ranking: xT and xT/90.
- xgchain_ranking: xGChain, xGBuildup and per-90 variants.
- carry_ranking: the bespoke "who carried their team" score.
- gk_ranking: goalkeepers ranked on goals-prevented (xG faced - goals), a
  documented PSxG proxy, kept entirely separate from the outfield list.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aggregate as agg
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_MINUTES: int = 180  # ~two full matches; floor for the headline outfield list.


def build_player_table(
    players_meta: pd.DataFrame,
    vaep: pd.DataFrame,
    xt: pd.DataFrame,
    chain: pd.DataFrame,
    teams: pd.DataFrame,
) -> pd.DataFrame:
    """Join all per-player metrics onto the minutes/position metadata table."""
    df = players_meta.merge(vaep, on="player_id", how="left")
    df = df.merge(xt, on="player_id", how="left")
    df = df.merge(chain, on="player_id", how="left")
    df = df.merge(teams.rename(columns={"team_name": "team"}), on="team_id", how="left")
    value_cols = ["vaep_raw", "vaep_adj", "off_raw", "def_raw", "xt", "xg_chain", "xg_buildup"]
    df[value_cols] = df[value_cols].fillna(0.0)
    return df


def overall_value_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """Outfield ranking on shrunk, opponent-adjusted VAEP per 90.

    Steps: filter outfield + minutes floor -> per-90 opponent-adjusted VAEP ->
    empirical-Bayes shrinkage toward the position-group mean.
    """
    out = df[(df["position_group"] != "GK") & (df["minutes"] >= MIN_MINUTES)].copy()
    out["vaep_adj_p90"] = agg.per90(out["vaep_adj"], out["minutes"])
    out["vaep_raw_p90"] = agg.per90(out["vaep_raw"], out["minutes"])
    out["vaep_adj_p90_shrunk"] = agg.shrink_per90(
        out, "vaep_adj", "minutes", "position_group"
    )
    out = out.sort_values("vaep_adj_p90_shrunk", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    cols = [
        "rank", "player_name", "team", "position_group", "primary_position",
        "minutes", "vaep_raw", "vaep_adj", "vaep_raw_p90", "vaep_adj_p90",
        "vaep_adj_p90_shrunk", "off_raw", "def_raw",
    ]
    return out[cols]


def per_position_top(overall: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Top-N per position group on the shrunk opponent-adjusted VAEP/90."""
    parts = []
    for grp in ["DEF", "MID", "FWD"]:
        sub = overall[overall["position_group"] == grp].head(top_n).copy()
        sub["pos_rank"] = range(1, len(sub) + 1)
        parts.append(sub)
    out = pd.concat(parts, ignore_index=True)
    cols = ["position_group", "pos_rank", "player_name", "team", "minutes",
            "vaep_adj_p90_shrunk", "vaep_adj"]
    return out[cols]


def xt_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """xT total and per-90, outfield, minutes floor."""
    out = df[(df["position_group"] != "GK") & (df["minutes"] >= MIN_MINUTES)].copy()
    out["xt_p90"] = agg.per90(out["xt"], out["minutes"])
    out = out.sort_values("xt", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out[["rank", "player_name", "team", "position_group", "minutes", "xt", "xt_p90"]]


def xgchain_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """xGChain / xGBuildup totals and per-90, outfield, minutes floor."""
    out = df[(df["position_group"] != "GK") & (df["minutes"] >= MIN_MINUTES)].copy()
    out["xg_chain_p90"] = agg.per90(out["xg_chain"], out["minutes"])
    out["xg_buildup_p90"] = agg.per90(out["xg_buildup"], out["minutes"])
    out = out.sort_values("xg_chain", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out[["rank", "player_name", "team", "position_group", "minutes",
                "xg_chain", "xg_buildup", "xg_chain_p90", "xg_buildup_p90"]]


def team_overachievement(games: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    """How far each team went vs a simple pre-tournament expectation.

    EXPECTATION MODEL AND LIMITATION:
        With no clean seed in the open data, we proxy "expected finish" by group-
        stage strength (goal difference per game over the first 3 games, i.e.
        ``game_day <= 3`` where available, else all games) and define
        overachievement as (rounds reached) minus (rounds the group-stage strength
        ranking would predict). Concretely we score actual progress by the
        knockout round each team reached and z-score it against group-stage GD.
        This rewards teams who advanced further than their group form implied
        (e.g. a side that scraped through the group then ran deep). Limitation:
        crude, conflates luck and genuine overperformance, and the final/winner
        gets the largest credit.

    Returns per team_id: rounds_reached, gd_group, overachievement (z-like score).
    """
    # Map competition_stage to a numeric "round reached" depth.
    stage_depth = {
        "Group Stage": 1,
        "Round of 16": 2,
        "Quarter-finals": 3,
        "Semi-finals": 4,
        "Final": 5,
    }
    games = games.copy()
    games["depth"] = games["competition_stage"].map(stage_depth).fillna(1)

    reached: dict[int, int] = {}
    for _, g in games.iterrows():
        d = int(g["depth"])
        for tid in (g["home_team_id"], g["away_team_id"]):
            reached[tid] = max(reached.get(tid, 0), d)

    # Group-stage GD per game as the "expectation" baseline.
    grp = games[games["competition_stage"] == "Group Stage"]
    rows: list[dict] = []
    for _, g in grp.iterrows():
        rows.append({"team_id": g["home_team_id"], "gd": g["home_score"] - g["away_score"]})
        rows.append({"team_id": g["away_team_id"], "gd": g["away_score"] - g["home_score"]})
    gd = pd.DataFrame(rows).groupby("team_id")["gd"].mean().rename("gd_group")

    out = pd.DataFrame({"rounds_reached": pd.Series(reached)})
    out = out.join(gd)
    out["gd_group"] = out["gd_group"].fillna(0.0)

    # Overachievement = z(rounds) - z(group GD): went far relative to group form.
    def _z(s: pd.Series) -> pd.Series:
        return (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0.0

    out["overachievement"] = _z(out["rounds_reached"]) - _z(out["gd_group"])
    # Shift to strictly positive multiplier range for the carry formula (min ~0.1).
    lo = out["overachievement"].min()
    out["overachievement_mult"] = out["overachievement"] - lo + 0.1
    return out.reset_index().rename(columns={"index": "team_id"})


def carry_ranking(
    df: pd.DataFrame, games: pd.DataFrame, teams: pd.DataFrame
) -> pd.DataFrame:
    """The bespoke "who carried their team" ranking.

    CARRY FORMULA:
        Carry = ValueShare x MinutesWeight x TeamOverachievement x Shrinkage
      where, per outfield player:
        ValueShare      = player VAEP (raw, positive part) / team total outfield VAEP
        MinutesWeight   = player minutes / max team minutes for one player slot
                          (proxied as minutes / (team games x 90)), capped at 1
        TeamOverachieve = team overachievement multiplier (see team_overachievement)
        Shrinkage       = minutes / (minutes + 270), the same reliability weight as
                          the EB shrinkage, so a small-sample player cannot top the
                          carry chart.

    Interpretation: a high carry score means the player took a large share of a
    successful (or overachieving) team's on-ball value while playing big minutes.
    This is deliberately team-relative, unlike the absolute VAEP/90 ranking.
    """
    over = team_overachievement(games, teams).set_index("team_id")

    # Team total positive outfield VAEP and games played.
    out = df[df["position_group"] != "GK"].copy()
    out["vaep_pos"] = out["vaep_raw"].clip(lower=0.0)
    team_total = out.groupby("team_id")["vaep_pos"].sum().rename("team_vaep")
    out = out.merge(team_total, on="team_id", how="left")

    # team games played (for minutes weight denominator).
    rows: list[dict] = []
    for _, g in games.iterrows():
        rows.append({"team_id": g["home_team_id"]})
        rows.append({"team_id": g["away_team_id"]})
    team_games = pd.DataFrame(rows).value_counts("team_id").rename("team_games")
    out = out.merge(team_games, on="team_id", how="left")

    out["value_share"] = np.where(out["team_vaep"] > 0, out["vaep_pos"] / out["team_vaep"], 0.0)
    out["minutes_weight"] = np.clip(out["minutes"] / (out["team_games"] * 90.0), 0.0, 1.0)
    out["overachievement_mult"] = out["team_id"].map(over["overachievement_mult"]).fillna(0.1)
    out["shrinkage"] = out["minutes"] / (out["minutes"] + 270.0)

    out["carry_score"] = (
        out["value_share"]
        * out["minutes_weight"]
        * out["overachievement_mult"]
        * out["shrinkage"]
    )
    out = out[out["minutes"] >= MIN_MINUTES]
    out = out.sort_values("carry_score", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    cols = ["rank", "player_name", "team", "position_group", "minutes",
            "value_share", "minutes_weight", "overachievement_mult", "shrinkage",
            "carry_score", "vaep_raw"]
    return out[cols]


def gk_ranking(
    gk_shots_faced: pd.DataFrame,
    players_meta: pd.DataFrame,
    teams: pd.DataFrame,
    min_shots: int = 8,
) -> pd.DataFrame:
    """Goalkeeper ranking on goals-prevented (PSxG proxy), kept separate.

    PSxG PROXY:
        StatsBomb open data does not expose post-shot xG. We therefore rank GKs on
        goals prevented = sum(pre-shot xG faced) - goals conceded. Positive means
        the keeper conceded fewer goals than the average finisher would have from
        those chances. This understates shot-stopping skill (pre-shot xG ignores
        shot placement/power that PSxG would capture) and is noisy over a short
        tournament, so we apply a minimum shots-faced floor.

    Returns per GK: shots_faced, xg_faced, goals_conceded, goals_prevented,
    goals_prevented_p90 (using GK minutes).
    """
    g = gk_shots_faced.groupby("player_id").agg(
        shots_faced=("xg_faced", "size"),
        xg_faced=("xg_faced", "sum"),
        goals_conceded=("goal_conceded", "sum"),
    ).reset_index()
    g["goals_prevented"] = g["xg_faced"] - g["goals_conceded"]

    meta = players_meta[players_meta["position_group"] == "GK"][
        ["player_id", "player_name", "team_id", "minutes"]
    ]
    g = g.merge(meta, on="player_id", how="left")
    g = g.merge(teams.rename(columns={"team_name": "team"}), on="team_id", how="left")
    g["goals_prevented_p90"] = agg.per90(g["goals_prevented"], g["minutes"].fillna(0.0))
    g = g[g["shots_faced"] >= min_shots]
    g = g.sort_values("goals_prevented", ascending=False).reset_index(drop=True)
    g.insert(0, "rank", g.index + 1)
    cols = ["rank", "player_name", "team", "minutes", "shots_faced", "xg_faced",
            "goals_conceded", "goals_prevented", "goals_prevented_p90"]
    return g[cols]


def write_all(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    """Write every ranking table to CSV in the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        path = output_dir / f"{name}.csv"
        table.to_csv(path, index=False)
        logger.info("wrote %s (%d rows)", path, len(table))
