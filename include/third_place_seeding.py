"""
World Cup 2026 third-place seeding + Round of 32 resolver.

Pure stdlib. JSON-in / JSON-out. No pandas, no network.

Pipeline:
    group standings  ->  rank the 12 third-placed teams  ->  take best 8
    ->  combo_key (8 sorted group letters)  ->  Annex C lookup
    ->  resolve all 16 Round-of-32 fixtures

Source of truth: FIFA "Regulations for the FIFA World Cup 26", Art. 13 (ranking)
and Annexe C (the 495 combinations). The Annex C table is shipped as
annex_c_map.json next to this file.
"""

from __future__ import annotations

import json
import os
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))

# winner-slot -> Round-of-32 match number (FIFA regs M73-M88)
SLOT_MATCH = {"1A": 79, "1B": 85, "1D": 81, "1E": 74,
              "1G": 82, "1I": 77, "1K": 87, "1L": 80}

# Static Round-of-32 structure. away_seed "3RD" is resolved via Annex C.
# eligible is the FIFA-published set of groups whose 3rd-placed team may land here.
R32 = [
    (73, "2A", "2B",  None),
    (74, "1E", "3RD", "ABCDF"),
    (75, "1F", "2C",  None),
    (76, "1C", "2F",  None),
    (77, "1I", "3RD", "CDFGH"),
    (78, "2E", "2I",  None),
    (79, "1A", "3RD", "CEFHI"),
    (80, "1L", "3RD", "EHIJK"),
    (81, "1D", "3RD", "BEFIJ"),
    (82, "1G", "3RD", "AEHIJ"),
    (83, "2K", "2L",  None),
    (84, "1H", "2J",  None),
    (85, "1B", "3RD", "EFGIJ"),
    (86, "1J", "2H",  None),
    (87, "1K", "3RD", "DEIJL"),
    (88, "2D", "2G",  None),
]


def load_annex_c(path: str | None = None) -> dict[str, dict[str, str]]:
    """combo_key (e.g. 'EFGHIJKL') -> {winner_slot: third_group_letter}."""
    path = path or os.path.join(HERE, "annex_c_map.json")
    with open(path) as f:
        return json.load(f)


def rank_third_placed(thirds: list[dict]) -> list[dict]:
    """
    Rank the 12 third-placed teams per FIFA Art. 13.
    Each team dict needs: group, points, gd, gf, conduct, fifa_rank.

      a) points            (higher better)
      b) goal difference   (higher better)
      c) goals for         (higher better)
      d) team conduct score(higher better; card deductions, see notes)
      e) FIFA/Coca-Cola Men's World Ranking (lower rank number = better)

    There is NO drawing of lots in 2026; the FIFA ranking is terminal.
    'conduct' defaults to 0 and 'fifa_rank' to a large sentinel if absent,
    so the function degrades gracefully when card/ranking data is missing.
    """
    return sorted(
        thirds,
        key=lambda t: (
            -t["points"],
            -t["gd"],
            -t["gf"],
            -t.get("conduct", 0),
            t.get("fifa_rank", 9999),
        ),
    )


def combo_key(qualified_thirds: list[dict]) -> str:
    """8 best thirds -> sorted group-letter key, e.g. ['E','J',...] -> 'EFGIJK..'."""
    return "".join(sorted(t["group"] for t in qualified_thirds))


def resolve_round_of_32(standings: dict, annex_c: dict | None = None) -> list[dict]:
    """
    standings = {
        "winners":   {"A": team, ... "L": team},   # 12 group winners
        "runners_up":{"A": team, ... "L": team},   # 12 runners-up
        "thirds":    {"A": team, ... "L": team},   # all 12 third-placed teams
    }
    Each `team` is any object; only the third-placed ones need the ranking
    fields above (group/points/gd/gf/conduct/fifa_rank).

    Returns 16 fixtures: {match_no, home_seed, away_seed, home, away}.
    """
    annex_c = annex_c or load_annex_c()

    thirds_list = list(standings["thirds"].values())
    if len(thirds_list) != 12:
        raise ValueError(f"expected 12 third-placed teams, got {len(thirds_list)}")

    best8 = rank_third_placed(thirds_list)[:8]
    key = combo_key(best8)
    if key not in annex_c:
        raise KeyError(f"combo_key {key!r} not in Annex C (should be 1 of 495)")

    slot_to_group = annex_c[key]                       # {'1A':'E', ...}
    third_by_group = {t["group"]: t for t in best8}

    def team_for(seed: str):
        kind, grp = seed[0], seed[1]
        if kind == "1":
            return standings["winners"][grp]
        if kind == "2":
            return standings["runners_up"][grp]
        raise ValueError(seed)

    fixtures = []
    for match_no, home_seed, away_seed, eligible in R32:
        home = team_for(home_seed)
        if away_seed == "3RD":
            grp = slot_to_group[home_seed]             # which 3rd lands on this winner
            assert grp in eligible, f"M{match_no}: 3{grp} not eligible ({eligible})"
            away = third_by_group[grp]
            away_label = f"3{grp}"
        else:
            away = team_for(away_seed)
            away_label = away_seed
        fixtures.append({
            "match_no": match_no,
            "home_seed": home_seed,
            "away_seed": away_label,
            "home": home,
            "away": away,
        })
    return fixtures


def self_test() -> None:
    """Validate the shipped table: 495 keys, perfect bijection, all eligible."""
    ac = load_annex_c()
    assert len(ac) == 495, len(ac)
    eligible = {"1A": set("CEFHI"), "1B": set("EFGIJ"), "1D": set("BEFIJ"),
                "1E": set("ABCDF"), "1G": set("AEHIJ"), "1I": set("CDFGH"),
                "1K": set("DEIJL"), "1L": set("EHIJK")}
    all_combos = {"".join(c) for c in combinations("ABCDEFGHIJKL", 8)}
    assert set(ac) == all_combos, "keys are not exactly C(12,8)"
    for key, assign in ac.items():
        groups = sorted(assign.values())
        assert "".join(groups) == key, (key, groups)        # row covers its own combo
        assert len(set(groups)) == 8
        for slot, g in assign.items():
            assert g in eligible[slot], (key, slot, g)
    print("self_test OK: 495 combos, bijection holds, all assignments eligible")


if __name__ == "__main__":
    self_test()
