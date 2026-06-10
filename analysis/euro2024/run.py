"""Single entry point that reproduces the entire Euro 2024 valuation analysis.

Pipeline:
    1. Load StatsBomb Euro 2024 open data and convert to SPADL (data.py).
    2. Fit xT and train VAEP, valuing every action (value_models.py).
    3. Aggregate per player, normalize per-90, apply opponent adjustment and
       Bayesian shrinkage; compute xGChain/xGBuildup (aggregate.py).
    4. Build and write all ranking CSVs incl. carry score and GK list (rankings.py).
    5. Optionally render figures.

Run:
    analysis/euro2024/.venv/bin/python analysis/euro2024/run.py
Optional flags:
    --force-refresh   ignore cache, re-download from StatsBomb.
    --no-figures      skip matplotlib figures.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import aggregate as agg
import data as data_mod
import pandas as pd
import rankings as rk
import value_models as vm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("euro2024.run")

ANALYSIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ANALYSIS_DIR / "output"


def make_figures(overall: pd.DataFrame, carry: pd.DataFrame, output_dir: Path) -> None:
    """Render simple bar-chart summaries of the headline rankings."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for table, value_col, title, fname in (
        (
            overall.head(15),
            "vaep_adj_p90_shrunk",
            "Top 15 outfield: shrunk opp-adj VAEP/90",
            "top_vaep.png",
        ),
        (carry.head(15), "carry_score", "Top 15 carry score", "top_carry.png"),
    ):
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.barh(table["player_name"][::-1], table[value_col][::-1], color="#1f77b4")
        ax.set_title(title)
        ax.set_xlabel(value_col)
        fig.tight_layout()
        fig.savefig(output_dir / fname, dpi=120)
        plt.close(fig)
        logger.info("wrote figure %s", output_dir / fname)


def main(force_refresh: bool = False, figures: bool = True) -> dict[str, pd.DataFrame]:
    """Run the full pipeline and return the ranking tables."""
    logger.info("=== Euro 2024 player-valuation analysis ===")

    # 1. Data + SPADL.
    bundle = data_mod.load_euro2024(OUTPUT_DIR, force_refresh=force_refresh)

    # 2. Action values.
    actions_xt = vm.compute_xt(bundle.actions, bundle.games)
    actions_valued = vm.compute_vaep(bundle.actions, bundle.games)
    # merge xT onto the valued actions by action identity.
    actions_valued = actions_valued.merge(
        actions_xt[["game_id", "action_id", "xt_value"]],
        on=["game_id", "action_id"],
        how="left",
    )
    actions_valued["xt_value"] = actions_valued["xt_value"].fillna(0.0)

    # 3. Aggregate.
    players_meta = agg.player_minutes_and_positions(bundle.players)
    strength = agg.opponent_strength(bundle.games)
    vaep_player = agg.opponent_adjusted_vaep(actions_valued, bundle.games, strength)
    xt_player = agg.sum_xt(actions_valued)
    chain_player = agg.xg_chain_buildup(bundle.possession_involvement, bundle.shots)

    player_table = rk.build_player_table(
        players_meta, vaep_player, xt_player, chain_player, bundle.teams
    )

    # 4. Rankings.
    overall = rk.overall_value_ranking(player_table)
    tables = {
        "overall_value_ranking": overall,
        "per_position_top": rk.per_position_top(overall),
        "xt_ranking": rk.xt_ranking(player_table),
        "xgchain_ranking": rk.xgchain_ranking(player_table),
        "carry_ranking": rk.carry_ranking(player_table, bundle.games, bundle.teams),
        "gk_ranking": rk.gk_ranking(bundle.gk_shots_faced, players_meta, bundle.teams),
    }
    rk.write_all(tables, OUTPUT_DIR)

    if figures:
        make_figures(tables["overall_value_ranking"], tables["carry_ranking"], OUTPUT_DIR)

    # Console summary.
    logger.info("\n=== TOP 10 OVERALL (shrunk opp-adj VAEP/90) ===\n%s",
                overall.head(10).to_string(index=False))
    logger.info("\n=== TOP 5 CARRY ===\n%s",
                tables["carry_ranking"].head(5).to_string(index=False))
    logger.info("\n=== TOP 5 GK (goals prevented) ===\n%s",
                tables["gk_ranking"].head(5).to_string(index=False))
    return tables


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Euro 2024 player-valuation analysis")
    parser.add_argument("--force-refresh", action="store_true", help="re-download data")
    parser.add_argument("--no-figures", action="store_true", help="skip figures")
    args = parser.parse_args()
    main(force_refresh=args.force_refresh, figures=not args.no_figures)
