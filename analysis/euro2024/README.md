# Euro 2024 player-valuation analysis

A reproducible, on-ball player-valuation study built on StatsBomb's FREE open
event data for UEFA Euro 2024 (men's), competition_id 55 / season_id 282. It
converts every match to SPADL actions and values players with four complementary
frameworks (xT, VAEP, xGChain/xGBuildup, and a bespoke "carry" score), with
opponent adjustment, per-90 normalization and empirical-Bayes shrinkage.

This directory is fully self-contained. It has its own virtual environment and
pinned `requirements.txt` and touches nothing outside `analysis/euro2024/`.

## How to reproduce

```bash
cd analysis/euro2024
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

`run.py` downloads the StatsBomb data on first run (cached to
`output/cache/*.parquet`), fits/trains the models, and writes every ranking CSV
plus two figures to `output/`. Re-running uses the cache; pass `--force-refresh`
to re-download and `--no-figures` to skip plotting.

## Package structure

| Module            | Responsibility |
|-------------------|----------------|
| `data.py`         | Download StatsBomb Euro 2024 data via socceraction's `StatsBombLoader`, convert each match to SPADL, extract minutes/positions, shot xG, goalkeeper shots-faced and possession-involvement chains. Caches everything to parquet. |
| `value_models.py` | Fit xT (16x12 grid) and train VAEP (two HistGradientBoosting classifiers under grouped cross-validation) to value every action. |
| `aggregate.py`    | Per-player aggregation, position grouping, opponent-strength weighting, xGChain/xGBuildup, per-90 normalization, empirical-Bayes shrinkage. |
| `rankings.py`     | Assemble the six ranking tables incl. the carry score and the goalkeeper list, and write CSVs. |
| `run.py`          | Single entry point that runs the whole pipeline. |

Outputs in `output/`: `overall_value_ranking.csv`, `per_position_top.csv`,
`xt_ranking.csv`, `xgchain_ranking.csv`, `carry_ranking.csv`, `gk_ranking.csv`,
plus `top_vaep.png` and `top_carry.png`.

## Metrics and modeling choices

### 1. SPADL conversion
Every StatsBomb match is converted to SPADL (Soccer Player Action Description
Language) with socceraction, giving a uniform action stream (passes, carries,
dribbles, shots, tackles, interceptions, clearances, etc.) with start/end
coordinates, result and body part. 51 matches yielded ~110,000 actions.

### 2. xT (expected threat)
A grid model: each pitch cell is valued by the long-run probability that
possession starting there ends in a goal. A successful move (pass or carry) is
credited the change in cell value it produces. The grid is fitted on the
tournament's own actions (16x12 cells), so the model is self-contained.

Important orientation detail: SPADL keeps both teams in one coordinate frame, so
the away team attacks right-to-left. xT's `fit`/`rate` assume attacking is
increasing-x, so we first reorient every game left-to-right per team
(`spadl.play_left_to_right`). Without this the model credits backward defensive
actions as progress and the leaderboard fills with center-backs; with it the
tournament total xT is positive and the leaders are the expected ball-carriers.

Bias: xT only values successful ball-progression moves. It ignores defending,
shot quality and turnovers, and gives no credit for off-ball movement.

### 3. VAEP (Valuing Actions by Estimating Probabilities)
The cross-position common currency. Each action changes two probabilities over
the next ~10 actions: P(team scores) and P(team concedes). VAEP value =
dP(score) - dP(concede), so a tackle or interception that kills a dangerous
attack is valued on the same goal-probability scale as a through-ball.

We build the standard socceraction feature set (action/body-part/result one-hots,
start/end location and polar coordinates, movement, time and space deltas, current
goal-score state) over game-states of 3 previous actions, then train two
`HistGradientBoostingClassifier` models (P_score, P_concede). To avoid leakage we
use `GroupKFold` by game (5 folds), so every action is scored out-of-fold by a
model that never saw its match. We sum VAEP per player.

Biases: VAEP is goal-probability driven, so it leans toward shots, key passes and
actions in dangerous zones. It is on-ball only (no gravity / off-ball value), and
over a single short tournament the score/concede labels are sparse (947 positive
"score" labels across ~110k actions), so the models are noisy.

### 4. xGChain and xGBuildup
Built from raw possession chains. For each possession we sum the StatsBomb shot
xG it produced, then:
- **xGChain(player)** = sum of possession xG over every possession the player was
  involved in (any on-ball event for the attacking team).
- **xGBuildup(player)** = the same, but excluding possessions where the player's
  only involvement was taking the shot or making the assisting key pass. This
  isolates pure build-up contribution and is the standard way to surface deep
  playmakers who do not rack up shots/assists.

Bias: a player on a high-volume attacking team accrues xGChain simply by being on
the pitch; it is a team-contextual, not isolated, metric.

### 5. Per-90 normalization
Minutes come directly from the StatsBomb lineup data (`minutes_played` summed per
player). All counting values are normalized to per-90.

### 6. Empirical-Bayes shrinkage
Per-90 rates are unstable on small samples. We shrink each player's per-90 VAEP
toward the minutes-weighted mean of his position group:

```
w      = minutes / (minutes + 270)         # 270 = three full matches
shrunk = w * player_per90 + (1 - w) * group_mean_per90
```

`prior_strength_minutes = 270` means a player needs roughly three full matches
before he is trusted over the group prior. Bias: this deliberately pulls extreme
small-sample performers toward the middle (a 20-minute cameo cannot top the
chart), at the cost of slightly under-rating genuine standouts with few minutes.

### 7. Opponent adjustment
Each action's VAEP is weighted by `0.5 + opponent_strength`, where
`opponent_strength` is a 0..1 min-max scaling of the opponent's goal-difference
per game across the tournament. Value generated against strong sides counts more
(weight up to ~1.5); the 0.5 floor stops the weakest opponent contributing zero.

Limitation (documented and important): with no clean pre-tournament FIFA/Elo seed
in the open data, this is a **within-tournament** proxy, hence circular: a team's
own results inform its "strength," and a team that conceded heavily reads as weak
even with decent underlying xG. It is a coarse correction, not a true ex-ante
seed. The `overall_value_ranking.csv` reports both raw (`vaep_raw_p90`) and
adjusted (`vaep_adj_p90`) so the effect is transparent.

### 8. Goalkeepers (handled separately)
GKs are excluded from every outfield list and ranked on their own table.
StatsBomb open data does **not** expose post-shot xG (PSxG), so we use a
documented proxy: **goals prevented = sum(pre-shot xG faced) - goals conceded**.
We match each "Goal Keeper" shot-faced/saved/conceded event to its shot via
`related_events` and attribute that shot's pre-shot xG to the keeper. Positive
means the keeper conceded fewer than an average finisher would from those chances.

Limitation: pre-shot xG ignores shot placement/power that true PSxG would capture,
so this understates pure shot-stopping skill, and it is noisy over a short
tournament (we apply an 8-shots-faced floor).

### 9. Carry score (who carried their team, distinct from "best")
A deliberately team-relative metric:

```
Carry = ValueShare x MinutesWeight x TeamOverachievement x Shrinkage
```

- **ValueShare** = player positive VAEP / team total positive outfield VAEP.
- **MinutesWeight** = minutes / (team games x 90), capped at 1 (did he play big
  minutes for the team?).
- **TeamOverachievement** = how far the team went versus a simple group-stage
  expectation. We score the knockout round reached (Group=1 ... Final=5) and
  subtract a z-score of group-stage goal-difference per game, then shift to a
  positive multiplier. A side that scraped through its group then ran deep scores
  highest; the finalists/winner get the largest credit.
- **Shrinkage** = minutes / (minutes + 270), the same reliability weight, so a
  small-sample player cannot top the carry chart.

Interpretation: high carry = a large slice of a successful (or overachieving)
team's on-ball value while playing heavy minutes. This is intentionally different
from the absolute VAEP/90 list.

Limitation: TeamOverachievement is crude and conflates luck with genuine
overperformance; ValueShare rewards being the focal point of a possession-heavy
side.

## Headline results

### Top 10 overall (shrunk, opponent-adjusted VAEP per 90, outfield only)

| Rank | Player | Team | Pos | Min | VAEP adj/90 (shrunk) |
|-----:|--------|------|-----|----:|---------------------:|
| 1 | Ivan Schranz | Slovakia | FWD | 349 | 0.503 |
| 2 | Florian Wirtz | Germany | FWD | 303 | 0.466 |
| 3 | Merih Demiral | Turkey | DEF | 236 | 0.430 |
| 4 | Donyell Malen | Netherlands | FWD | 204 | 0.413 |
| 5 | Francisco Conceicao | Portugal | MID | 201 | 0.362 |
| 6 | Randal Kolo Muani | France | FWD | 219 | 0.357 |
| 7 | Breel Embolo | Switzerland | FWD | 315 | 0.346 |
| 8 | Jamal Musiala | Germany | FWD | 443 | 0.309 |
| 9 | Alessandro Bastoni | Italy | DEF | 390 | 0.297 |
| 10 | Cody Gakpo | Netherlands | FWD | 558 | 0.294 |

### Top 5 carry score

| Rank | Player | Team | Pos | Min | Carry |
|-----:|--------|------|-----|----:|------:|
| 1 | Cody Gakpo | Netherlands | FWD | 558 | 0.526 |
| 2 | Ivan Schranz | Slovakia | FWD | 349 | 0.489 |
| 3 | Jules Kounde | France | DEF | 607 | 0.433 |
| 4 | Jude Bellingham | England | MID | 707 | 0.411 |
| 5 | Harry Kane | England | FWD | 629 | 0.388 |

### xT leaders (ball progression): Lamine Yamal, Cody Gakpo, Jeremy Doku, Nico Williams, Bukayo Saka.
### xGChain leaders: Cristiano Ronaldo, Fabian Ruiz, Kai Havertz, Toni Kroos, Bernardo Silva.
### Top goalkeepers (goals prevented): Koen Casteels (+2.93), Mike Maignan (+2.86), Jan Oblak (+2.67), Giorgi Mamardashvili (+2.39), Mert Gunok (+2.19).

## Face-validity assessment

**Honest verdict: mostly credible, with one well-understood distortion at the very
top of the VAEP/90 list.**

What lands correctly:
- **xT** is the cleanest. Its top five (Yamal, Gakpo, Doku, Nico Williams, Saka)
  are exactly the players everyone watched drive the ball forward at Euro 2024.
  Yamal, the tournament's breakout star and Best Young Player, is the clear #1.
- **xGChain** correctly surfaces the deep orchestrators of the deepest teams:
  Spain's Fabian Ruiz and Germany's Toni Kroos, plus high-volume forwards
  (Ronaldo, Havertz, Bernardo Silva). xGBuildup (Kroos, Fabian Ruiz top) isolates
  the pure build-up creators as intended.
- **Carry** is arguably the most interpretable list and has strong face validity:
  Gakpo (Netherlands' top scorer, ran to the semis) at #1, Bellingham and Kane
  (England, beaten finalists) in the top 5, and Kounde anchoring France's run.
  These are genuinely the players who shouldered deep-running sides.
- **Goalkeepers**: Maignan (France conceded almost nothing in open play) and
  Mamardashvili (faced a tournament-high shot volume for Georgia) both ranking
  highly is sensible; Casteels topping it on a small-but-clean Belgium sample is
  the expected noise of a short tournament.
- The known stars are present and reasonably placed in the full overall table:
  Musiala #8, Dani Olmo #12, Yamal #13, Fabian Ruiz #25; per-position tops include
  Dani Olmo (MID) and Bastoni (DEF).

The distortion to be honest about (why #1 is Ivan Schranz, not Yamal/Olmo/Rodri):
- The headline `overall_value_ranking` is **VAEP per 90**, and VAEP is heavily
  goal-probability driven. Players who scored or created very efficiently in
  **limited minutes** (Schranz 349 min, 3 group-stage goals; Wirtz 303; Demiral
  236, two goals incl. the fastest in Euros history) post huge per-90 rates.
- Shrinkage (prior 270 minutes) softens this but does not erase it, because these
  players still cleared the three-match-equivalent threshold. The metric is
  literally answering "highest goal-probability value added per minute on the
  pitch," and on that question a hot, low-minutes finisher genuinely tops it. It is
  **not** answering "who was the best/most valuable player overall," which is what
  a casual reader expects #1 to mean.
- This is the standard VAEP/90 small-sample, finishing-variance artifact, not a
  bug. The tournament's consensus best player (Rodri, who won player of the
  tournament) ranks low (#150) precisely because VAEP under-credits
  metronomic, low-risk deep midfield control: his actions rarely swing the
  immediate score/concede probability, so the on-ball model barely sees his value.
  This is the clearest illustration of VAEP's blind spot.

So: if asked "who was the best player," the **carry score** and the **total**
(not per-90) value columns are more faithful than the per-90 headline. The per-90
list is correct for what it measures and is left as the headline for methodological
honesty, with this caveat documented.

## Limitations (summary)
- **On-ball only.** No off-ball movement, pressing decoy runs, defensive
  positioning or "gravity." A player who creates space without touching the ball
  is invisible to every metric here.
- **Small samples.** A 51-match tournament with sparse goal labels makes VAEP
  models noisy and per-90 rates volatile; shrinkage mitigates but cannot fix this.
- **Opponent adjustment is a within-tournament proxy** and therefore circular; it
  is a coarse correction, not a true pre-tournament seed.
- **GK PSxG is a pre-shot-xG proxy**, understating shot-stopping skill.
- **Carry's TeamOverachievement is crude** and conflates luck with merit.
- VAEP systematically under-credits low-event, low-risk controllers (the Rodri
  effect) and over-credits efficient finishers in small minutes (the Schranz
  effect). Read the per-90 headline with that in mind.
