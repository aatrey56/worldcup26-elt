"""
int_projected_r32: the projected Round of 32, resolved from the LIVE provisional
group standings "as things stand".

This is a dbt-duckdb PYTHON model (not SQL) because the third-place seeding is
procedural: which group's third-placed team faces which group winner depends on
WHICH 8 of the 12 thirds qualify (FIFA Annexe C, 495 combinations), which a SQL
join cannot express cleanly. We reuse the committed, self-tested resolver in
include/third_place_seeding.py (do NOT reimplement the table here).

Flow (per the spec, docs/THIRD_PLACE_SEEDING.md):
  int_group_table_live  ->  winners / runners-up / thirds per group
  ->  resolve_round_of_32()  ->  16 R32 fixtures (8 winner-vs-third via Annexe C,
      8 winner/runner-up matchups that need no lookup).

The 8 winner-vs-runner-up matchups project from current standings immediately.
The 8 third-place slots are recomputed from current standings on EVERY run (never
cached): the combo_key churns while the group stage is in flux, which is the
intended "as things stand" behaviour. is_provisional is true until all 72 group
matches are final (every team has played 3), then the matchups are locked.

Grain: one row per R32 fixture (16 rows, match_no 73-88).
"""

import os
import sys

import pandas as pd


def _repo_root() -> str:
    # dbt-duckdb runs python models with cwd = the dbt project dir, so the repo
    # root is its parent (that is where include/ lives). REPO_ROOT overrides this
    # for any environment where the cwd assumption does not hold.
    return os.environ.get("REPO_ROOT") or os.path.abspath(os.path.join(os.getcwd(), os.pardir))


def model(dbt, session):
    dbt.config(materialized="table")

    sys.path.insert(0, _repo_root())
    from include.third_place_seeding import resolve_round_of_32

    standings = dbt.ref("int_group_table_live").df()

    # Build the per-group winner / runner-up / third from the provisional ranks.
    # int_group_table_live always carries all 48 teams, so every group has a
    # determinate rank 1/2/3 (the resolver requires all 12 thirds).
    winners, runners_up, thirds = {}, {}, {}
    for row in standings.itertuples(index=False):
        team = {
            "group": row.group_letter,
            "team_name": row.team_name,
            "points": int(row.points),
            "gd": int(row.gd),
            "gf": int(row.gf),
            # conduct / fifa_rank are not in the warehouse; the resolver defaults
            # them, degrading Art. 13 to points/GD/GF (see spec notes).
        }
        if row.rank == 1:
            winners[row.group_letter] = team
        elif row.rank == 2:
            runners_up[row.group_letter] = team
        elif row.rank == 3:
            thirds[row.group_letter] = team

    fixtures = resolve_round_of_32(
        {"winners": winners, "runners_up": runners_up, "thirds": thirds}
    )

    # Locked once every group team has played its 3 matches; provisional before.
    all_group_games_final = bool(
        len(standings) == 48 and int(standings["played"].min()) >= 3
    )

    records = []
    for fx in fixtures:
        records.append(
            {
                "match_no": int(fx["match_no"]),
                "home_seed": fx["home_seed"],
                "away_seed": fx["away_seed"],
                "home_team": fx["home"]["team_name"],
                "away_team": fx["away"]["team_name"],
                "home_group": fx["home"]["group"],
                "away_group": fx["away"]["group"],
                "is_provisional": not all_group_games_final,
            }
        )

    return pd.DataFrame.from_records(
        records,
        columns=[
            "match_no",
            "home_seed",
            "away_seed",
            "home_team",
            "away_team",
            "home_group",
            "away_group",
            "is_provisional",
        ],
    )
