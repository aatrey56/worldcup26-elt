"""
int_group_clinch: per (group, position) flag for whether the team currently in a
group position has MATHEMATICALLY clinched finishing in EXACTLY that position,
given the results played so far.

A position p (1st/2nd/3rd/4th of a group) is "clinched" for the team holding it
when NO completion of the remaining group fixtures (any results, any scorelines)
can move that team out of position p. The bracket page renders a "(!)" confirmed
marker on a slot whose team's position is clinched, and "(proj)" otherwise.

Grain: one row per (group_letter, position) over the 12 groups x 4 positions (48
rows once every group has its 4 teams). team_name is the team in that position in
the live standings (int_group_table_live); is_clinched is the confirmation flag.

HOW IT WORKS (head-to-head aware)
  Each group is a 4-team round robin: 6 fixtures, 3 per team. We read the finished
  group results (int_results_scored, is_live = false) and the group's 6 scheduled
  fixtures (stg_schedule), and the current rank of each team
  (int_group_table_live) so a position maps to the same team the page shows.
  For a group with k remaining fixtures we enumerate every win/draw/loss outcome
  of those fixtures (3^k, k <= 6). For each outcome we compute every team's
  points, and for the teams level on points we compute their HEAD-TO-HEAD points
  (FIFA Art. 13 step one: points in the matches between the teams concerned) -
  which depends only on results, not on scorelines.

  For a team T at position p, in each outcome we count:
    - possibly_above(T): teams that could finish above T = teams with more points,
      plus teams level on points that are NOT below T on head-to-head (i.e. their
      head-to-head points are >= T's). A level team that is only ahead on goal
      difference is "possible" because goal margins are not enumerated.
    - definitely_above(T): teams certain to finish above T = teams with more
      points, plus teams level on points with STRICTLY greater head-to-head
      points (head-to-head settles it regardless of goals).
  T has clinched EXACTLY position p when, in EVERY outcome,
  possibly_above(T) <= p-1 (guaranteed no worse than p) AND definitely_above(T)
  >= p-1 (guaranteed no better than p).

  A completed group (zero remaining fixtures) is final by definition, so every
  position is clinched.

SOUNDNESS (never a false positive)
  Goal margins are unbounded and are NOT enumerated. The only ties we resolve are
  the ones FIFA settles before goal difference, i.e. head-to-head points among the
  level teams. Any tie that head-to-head leaves level is treated as still open
  (the level team counts as "possibly above"), because a scoreline could flip it
  on goal difference or on the criteria below. So a clinch via head-to-head (e.g.
  a team that has beaten everyone who can match its points) is reported, while a
  goal-difference-dependent lead is conservatively left unclinched. This can
  report a clinch a little later than a fully goal-aware solver, but never reports
  one that is not real.

EDGE CASES
  - No games played: every team can still be caught on points, nothing clinched.
  - Group complete: final, every position clinched.

Empty-safe: pre-tournament int_results_scored is empty, every group has 6
remaining fixtures, nothing is clinched. A group with no scheduled fixtures
contributes no rows.
"""

from itertools import product

import pandas as pd

# remaining-fixture outcome -> (home_points, away_points). Goals are not modelled.
_OUTCOME_POINTS = {"H": (3, 0), "D": (1, 1), "A": (0, 3)}


def _all_matches(played, remaining, combo):
    """played results plus the remaining fixtures resolved by `combo`.

    Each entry is (home, away, home_points, away_points)."""
    matches = list(played)
    for (home, away), outcome in zip(remaining, combo, strict=True):
        hp, ap = _OUTCOME_POINTS[outcome]
        matches.append((home, away, hp, ap))
    return matches


def _points(matches, teams):
    pts = {t: 0 for t in teams}
    for home, away, hp, ap in matches:
        if home in pts:
            pts[home] += hp
        if away in pts:
            pts[away] += ap
    return pts


def _h2h_points(matches, subset):
    """FIFA step-one head-to-head points: points won in matches where BOTH teams
    are in `subset`. Depends only on results, not scorelines."""
    hp = {t: 0 for t in subset}
    for home, away, hpp, app in matches:
        if home in subset and away in subset:
            hp[home] += hpp
            hp[away] += app
    return hp


def clinch_exact(teams, played, remaining, team, position):
    """True iff `team` is guaranteed to finish in EXACTLY `position` (1-indexed)
    over every completion of the remaining fixtures. Head-to-head aware, goal
    difference agnostic, sound (never a false positive). See module docstring."""
    if not remaining:
        # group complete: the standings are final, so the position is locked.
        return True

    at_most = True   # guaranteed no worse than `position`
    at_least = True  # guaranteed no better than `position`
    for combo in product("HDA", repeat=len(remaining)):
        matches = _all_matches(played, remaining, combo)
        pts = _points(matches, teams)
        team_pts = pts[team]
        level = [t for t in teams if pts[t] == team_pts]
        h2h = _h2h_points(matches, set(level))

        possibly_above = 0
        definitely_above = 0
        for other in teams:
            if other == team:
                continue
            if pts[other] > team_pts:
                possibly_above += 1
                definitely_above += 1
            elif pts[other] == team_pts:
                # level on points: head-to-head (step one) decides what it can
                if h2h[other] > h2h[team]:
                    possibly_above += 1
                    definitely_above += 1
                elif h2h[other] == h2h[team]:
                    # head-to-head level too: goal margins (not modelled) could
                    # still put it above, so it is possible but not definite.
                    possibly_above += 1
        if possibly_above > position - 1:
            at_most = False
        if definitely_above < position - 1:
            at_least = False
        if not at_most and not at_least:
            break
    return at_most and at_least


def model(dbt, session):
    dbt.config(materialized="table")

    schedule = dbt.ref("stg_schedule").df()
    results = dbt.ref("int_results_scored").df()
    standings = dbt.ref("int_group_table_live").df()

    group_fixtures = schedule[schedule["stage"] == "group"]

    # finished group results only (exclude in-play rows, like the standings)
    if len(results) > 0 and "is_live" in results.columns:
        finished = results[~results["is_live"].astype(bool)]
    else:
        finished = results.iloc[0:0]
    finished_match_nos = set(int(m) for m in finished["match_no"].tolist())

    # banked finished results keyed by match_no, as (home, away, hp, ap)
    banked = {
        int(r.match_no): (r.home_team, r.away_team, int(r.home_points), int(r.away_points))
        for r in finished.itertuples(index=False)
    }

    # current rank per team (so a position maps to the team the page shows)
    rank_of = {
        (r.group_letter, r.team_name): int(r.rank)
        for r in standings.itertuples(index=False)
    }

    records = []

    for group_letter, grp in group_fixtures.groupby("group_letter"):
        if pd.isna(group_letter):
            continue

        teams = sorted(set(grp["home_team"]).union(set(grp["away_team"])))

        played, remaining = [], []
        for fx in grp.itertuples(index=False):
            mn = int(fx.match_no)
            if mn in finished_match_nos and mn in banked:
                played.append(banked[mn])
            else:
                remaining.append((fx.home_team, fx.away_team))

        for team in teams:
            position = rank_of.get((group_letter, team))
            if position is None:
                continue
            records.append(
                {
                    "group_letter": group_letter,
                    "position": position,
                    "team_name": team,
                    "is_clinched": bool(
                        clinch_exact(teams, played, remaining, team, position)
                    ),
                }
            )

    return pd.DataFrame.from_records(
        records,
        columns=["group_letter", "position", "team_name", "is_clinched"],
    )


def self_test():
    teams = ["A", "B", "C", "D"]

    # Head-to-head clinch (the USA / Germany case): A has beaten both chasers
    # (B and C), who play EACH OTHER in the last round, so only one can reach A's
    # points and A won that head-to-head. A is locked as 1st even though it is not
    # points-separated (a chaser can match its points).
    played = [("A", "B", 3, 0), ("A", "C", 3, 0), ("B", "D", 3, 0), ("C", "D", 3, 0)]
    remaining = [("A", "D"), ("B", "C")]
    assert clinch_exact(teams, played, remaining, "A", 1), "A should clinch 1st on head-to-head"

    # Not clinched: a chaser can OUT-POINT the leader. A=6 but B (on 4) plays A
    # last and can win to reach 7, so A is not guaranteed 1st.
    played2 = [("A", "C", 3, 0), ("A", "D", 3, 0), ("B", "C", 1, 1), ("B", "D", 3, 0)]
    remaining2 = [("A", "B"), ("C", "D")]
    assert not clinch_exact(teams, played2, remaining2, "A", 1), "A can be out-pointed"

    # Head-to-head level => not clinched (goal difference could decide). A and B
    # drew, both on 6, last games vs the weak C/D; either could top on goals.
    played3 = [("A", "B", 1, 1), ("A", "C", 3, 0), ("B", "D", 3, 0)]
    remaining3 = [("A", "D"), ("B", "C")]
    assert not clinch_exact(teams, played3, remaining3, "A", 1), "level h2h is no clinch"

    # Completed group: final, so every position is clinched.
    played4 = [
        ("A", "B", 3, 0), ("A", "C", 3, 0), ("A", "D", 3, 0),
        ("B", "C", 3, 0), ("B", "D", 3, 0), ("C", "D", 3, 0),
    ]
    assert clinch_exact(teams, played4, [], "A", 1), "complete group is final"
    assert clinch_exact(teams, played4, [], "D", 4), "complete group is final"

    print("int_group_clinch self_test passed")


if __name__ == "__main__":
    self_test()
