"""Data ingestion for the Euro 2024 player-valuation analysis.

Pulls StatsBomb FREE open event data for UEFA Euro 2024 (men's) via socceraction's
``StatsBombLoader`` and converts every match to SPADL (Soccer Player Action
Description Language) actions. Also extracts player minutes, positions, shot-level
xG, goalkeeper shot-faced records and a per-match game index.

All data is cached to local parquet under ``output/cache/`` so reruns are fast and
the network is only hit once.

StatsBomb identifiers (verified via ``StatsBombLoader.competitions()``):
    competition_id = 55  ("UEFA Euro")
    season_id      = 282 ("2024")
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import socceraction.spadl as spadl
from socceraction.data.statsbomb import StatsBombLoader

logger = logging.getLogger(__name__)

COMPETITION_ID: int = 55
SEASON_ID: int = 282

# socceraction emits a lot of pandas FutureWarnings during conversion; silence them
# so the structured logs stay readable. This does not affect correctness.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class Euro2024Data:
    """Container for all loaded and converted Euro 2024 data.

    Attributes:
        games: One row per match (game_id, teams, scores, date, stage).
        actions: SPADL actions for every match with ``add_names`` applied.
        players: Per game-player rows with minutes_played and starting position.
        teams: team_id -> team_name lookup.
        shots: Shot-level frame with statsbomb_xg, possession, key_pass_id.
        gk_shots_faced: Goalkeeper shot-faced records with the faced shot xG and
            whether the shot became a goal (for the PSxG-proxy GK ranking).
        possession_involvement: One row per (game, possession, player) recording
            every player who touched the ball in a possession, plus whether the
            event was that player's shot or key pass (for xGChain / xGBuildup).
    """

    games: pd.DataFrame
    actions: pd.DataFrame
    players: pd.DataFrame
    teams: pd.DataFrame
    shots: pd.DataFrame
    gk_shots_faced: pd.DataFrame
    possession_involvement: pd.DataFrame


def _cache_dir(output_dir: Path) -> Path:
    cache = output_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _extract_shots(events: pd.DataFrame) -> pd.DataFrame:
    """Pull shot xG and possession metadata from raw StatsBomb events.

    Returns one row per shot with: game_id, possession, possession_team_id,
    player_id, team_id, statsbomb_xg, is_goal, key_pass_id.
    """
    rows: list[dict] = []
    shot_events = events[events["type_name"] == "Shot"]
    for _, ev in shot_events.iterrows():
        shot = ev["extra"].get("shot", {})
        outcome = shot.get("outcome", {}) or {}
        rows.append(
            {
                "game_id": ev["game_id"],
                "event_id": ev["event_id"],
                "possession": ev["possession"],
                "possession_team_id": ev["possession_team_id"],
                "player_id": ev["player_id"],
                "team_id": ev["team_id"],
                "statsbomb_xg": float(shot.get("statsbomb_xg", 0.0) or 0.0),
                "is_goal": outcome.get("name") == "Goal",
                "key_pass_id": shot.get("key_pass_id"),
            }
        )
    return pd.DataFrame(rows)


def _extract_gk_shots_faced(events: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """Build goalkeeper "shot faced" records.

    StatsBomb open data does NOT expose a post-shot xG (PSxG) field. We therefore
    construct a documented proxy: for every "Goal Keeper" event of type "Shot
    Faced" / "Shot Saved" / "Goal Conceded", we attribute the corresponding shot's
    pre-shot xG to the goalkeeper as "xG faced", and record whether the shot was a
    goal. Goals-prevented = sum(xG faced) - goals conceded.

    Matching: a goalkeeper shot-faced event references the shot via its
    related_events. We match on the related shot event_id; falling back to the
    nearest preceding shot by index within the same game when not present.
    """
    rows: list[dict] = []
    shot_xg = shots.set_index("event_id")["statsbomb_xg"].to_dict()
    shot_goal = shots.set_index("event_id")["is_goal"].to_dict()

    gk_events = events[events["type_name"] == "Goal Keeper"].copy()
    for _, ev in gk_events.iterrows():
        gk = ev["extra"].get("goalkeeper", {}) or {}
        gk_type = (gk.get("type", {}) or {}).get("name")
        if gk_type not in {"Shot Faced", "Shot Saved", "Goal Conceded"}:
            continue
        related = ev.get("related_events") or []
        faced_xg = None
        faced_goal = None
        for rel in related:
            if rel in shot_xg:
                faced_xg = shot_xg[rel]
                faced_goal = shot_goal[rel]
                break
        if faced_xg is None:
            # Could not match a shot; skip rather than fabricate.
            continue
        rows.append(
            {
                "game_id": ev["game_id"],
                "player_id": ev["player_id"],
                "team_id": ev["team_id"],
                "xg_faced": float(faced_xg),
                "goal_conceded": bool(faced_goal),
            }
        )
    return pd.DataFrame(rows)


def _extract_possession_involvement(
    events: pd.DataFrame, shots: pd.DataFrame
) -> pd.DataFrame:
    """Record which players were involved in each possession (for xGChain).

    A player is "involved" in a possession if they have any on-ball event in it
    for the possession team. We also flag, per (possession, player), whether the
    player took a shot in that possession and whether they made the key pass that
    assisted a shot (so xGBuildup can exclude shots and key passes).

    Returns one row per (game_id, possession, player_id) with flags ``took_shot``
    and ``made_key_pass``.
    """
    # event_id -> True for shots; key_pass_id set for key passes.
    key_pass_ids = set(shots["key_pass_id"].dropna().tolist())

    on_ball = events[events["player_id"].notna()].copy()
    # restrict involvement to events by the possession team (attacking chain)
    on_ball = on_ball[on_ball["team_id"] == on_ball["possession_team_id"]]
    on_ball["took_shot"] = on_ball["type_name"] == "Shot"
    on_ball["made_key_pass"] = on_ball["event_id"].isin(key_pass_ids)

    grp = (
        on_ball.groupby(["game_id", "possession", "player_id"], as_index=False)
        .agg(took_shot=("took_shot", "max"), made_key_pass=("made_key_pass", "max"))
    )
    return grp


def load_euro2024(output_dir: Path, force_refresh: bool = False) -> Euro2024Data:
    """Load (or rebuild) all Euro 2024 data and SPADL actions.

    Args:
        output_dir: Analysis output directory; cache lives under ``cache/``.
        force_refresh: If True, ignore cache and re-download from StatsBomb.

    Returns:
        Euro2024Data bundle.
    """
    cache = _cache_dir(output_dir)
    paths = {
        "games": cache / "games.parquet",
        "actions": cache / "actions.parquet",
        "players": cache / "players.parquet",
        "teams": cache / "teams.parquet",
        "shots": cache / "shots.parquet",
        "gk": cache / "gk_shots_faced.parquet",
        "poss": cache / "possession_involvement.parquet",
    }

    if not force_refresh and all(p.exists() for p in paths.values()):
        logger.info("loading data from cache at %s", cache)
        return Euro2024Data(
            games=pd.read_parquet(paths["games"]),
            actions=pd.read_parquet(paths["actions"]),
            players=pd.read_parquet(paths["players"]),
            teams=pd.read_parquet(paths["teams"]),
            shots=pd.read_parquet(paths["shots"]),
            gk_shots_faced=pd.read_parquet(paths["gk"]),
            possession_involvement=pd.read_parquet(paths["poss"]),
        )

    logger.info("downloading Euro 2024 data from StatsBomb open data (no cache)")
    loader = StatsBombLoader(getter="remote")
    games = loader.games(COMPETITION_ID, SEASON_ID)
    logger.info("found %d games", len(games))

    all_actions: list[pd.DataFrame] = []
    all_players: list[pd.DataFrame] = []
    all_teams: list[pd.DataFrame] = []
    all_shots: list[pd.DataFrame] = []
    all_gk: list[pd.DataFrame] = []
    all_poss: list[pd.DataFrame] = []

    for i, game in games.iterrows():
        game_id = int(game["game_id"])
        home_team_id = int(game["home_team_id"])
        logger.info("processing game %d/%d (game_id=%d)", i + 1, len(games), game_id)

        events = loader.events(game_id)
        actions = spadl.statsbomb.convert_to_actions(events, home_team_id=home_team_id)
        actions = spadl.add_names(actions)
        all_actions.append(actions)

        all_players.append(loader.players(game_id))
        all_teams.append(loader.teams(game_id))

        shots = _extract_shots(events)
        all_shots.append(shots)
        all_gk.append(_extract_gk_shots_faced(events, shots))
        all_poss.append(_extract_possession_involvement(events, shots))

    actions_df = pd.concat(all_actions, ignore_index=True)
    players_df = pd.concat(all_players, ignore_index=True)
    teams_df = pd.concat(all_teams, ignore_index=True).drop_duplicates("team_id")
    shots_df = pd.concat(all_shots, ignore_index=True)
    gk_df = pd.concat(all_gk, ignore_index=True)
    poss_df = pd.concat(all_poss, ignore_index=True)

    # Attach player_name to actions via the players table (per game-player).
    name_lookup = (
        players_df[["player_id", "player_name"]]
        .drop_duplicates("player_id")
        .set_index("player_id")["player_name"]
    )
    actions_df["player_name"] = actions_df["player_id"].map(name_lookup)

    actions_df.to_parquet(paths["actions"])
    games.to_parquet(paths["games"])
    players_df.to_parquet(paths["players"])
    teams_df.to_parquet(paths["teams"])
    shots_df.to_parquet(paths["shots"])
    gk_df.to_parquet(paths["gk"])
    poss_df.to_parquet(paths["poss"])
    logger.info("cached all data to %s", cache)

    return Euro2024Data(
        games=games,
        actions=actions_df,
        players=players_df,
        teams=teams_df,
        shots=shots_df,
        gk_shots_faced=gk_df,
        possession_involvement=poss_df,
    )
