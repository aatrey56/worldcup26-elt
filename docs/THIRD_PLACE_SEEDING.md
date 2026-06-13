# Third-Place Seeding + Round of 32 (WC2026 pipeline)

Implementation handoff. Everything here is verified against FIFA’s official
“Regulations for the FIFA World Cup 26” (Art. 13 ranking, Annexe C combinations).
Source PDF: digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf

No drawing of lots exists in 2026. The bracket is fully deterministic once group
results are final, so this can run unattended on the 6-hour refresh.

## Files in this drop

|File                             |Role                                                                                       |
|---------------------------------|-------------------------------------------------------------------------------------------|
|`annex_c_third_place_seeding.csv`|dbt seed. Long format, 3960 rows (495 combos x 8 slots). The lookup table.                 |
|`r32_match_structure.csv`        |dbt seed. 16 rows. Static Round-of-32 shape (M73 to M88).                                  |
|`annex_c_map.json`               |Same table as compact JSON for the Python/app side. 495 keys.                              |
|`third_place_seeding.py`         |Pure-stdlib resolver: rank thirds, build key, apply Annex C, fill R32. Has a `self_test()`.|

## The rule, in two layers

Layer 1, ranking the 12 third-placed teams (Art. 13). Take the best 8. Criteria
in strict order:

1. Points (all group matches)
1. Goal difference (all group matches)
1. Goals scored (all group matches)
1. Team conduct score (card deductions, higher is better)
1. FIFA/Coca-Cola Men’s World Ranking, most recent edition, then prior editions

Conduct-score deductions, max one per player or official per match:
yellow -1, indirect red (two yellows) -3, direct red -4, yellow plus direct red -5.

Layer 2, seeding the 8 thirds into the bracket (Annexe C). This is the part you
cannot derive from a simple sort. The Round-of-32 opponent of each third depends
on WHICH groups the 8 qualifiers came from, not on their 1-to-8 rank. There are
C(12,8) = 495 possible group sets, each with a fixed slot assignment.

Mechanism: take the 8 qualifying third-placed teams, sort their group letters,
concatenate into a `combo_key` (e.g. `EFGHIJKL`). Look that key up in the table.
You get a map from winner-slot to third-place group:
`{"1A":"E","1B":"J","1D":"I","1E":"F","1G":"H","1I":"G","1K":"L","1L":"K"}`.
The slot `1A` is the winner of Group A, and so on. Only 8 winners face thirds:
A, B, D, E, G, I, K, L.

## Round of 32 structure (static)

8 of the 16 matches pit a group winner against a best-third. The other 8 are
winner-vs-runner-up or runner-up-vs-runner-up and need no Annex C lookup.

|Match|Home|Away|Eligible thirds|
|-----|----|----|---------------|
|73   |RU A|RU B|-              |
|74   |W E |3rd |A B C D F      |
|75   |W F |RU C|-              |
|76   |W C |RU F|-              |
|77   |W I |3rd |C D F G H      |
|78   |RU E|RU I|-              |
|79   |W A |3rd |C E F H I      |
|80   |W L |3rd |E H I J K      |
|81   |W D |3rd |B E F I J      |
|82   |W G |3rd |A E H I J      |
|83   |RU K|RU L|-              |
|84   |W H |RU J|-              |
|85   |W B |3rd |E F G I J      |
|86   |W J |RU H|-              |
|87   |W K |3rd |D E I J L      |
|88   |RU D|RU G|-              |

FIFA guarantees no same-group rematch in the R32, baked into the table, so you do
not need to enforce it yourself. Match numbers are bracket position, not kickoff
order.

## Integration into the existing stack

Recommended split: keep the two CSVs as dbt seeds (they are static reference data),
and do the ranking + lookup in the Python resolver, since the third-place ranking
is procedural and the conduct-score tiebreaker may need data your warehouse does
not hold yet.

1. `dbt seed` both CSVs into DuckDB. They sit alongside `fct_result`.
1. Build a `stg_group_standings` model off `fct_result`: for each of the 12 groups
   compute points, GD, GF per team and assign position 1/2/3/4. You already have
   the fact table and tests for this.
1. Resolve seeding. Either:
- Python path (simplest): pull winners/runners-up/thirds out of DuckDB, call
  `resolve_round_of_32(standings)`, write the 16 fixtures back to a table. The
  resolver is JSON-in/JSON-out and has no deps.
- Pure-SQL path: rank thirds in a model, derive `combo_key` with a string_agg of
  the sorted third-place group letters, join to
  `annex_c_third_place_seeding` on `combo_key`, then join `r32_match_structure`
  to attach the winner/runner-up teams. Heavier in SQL but keeps it all in dbt.
1. Feed the resolved R32 winners into the next round. R16 onward is static
   winner-of-MX-vs-winner-of-MY, not included here (ask if you want that seed too).

## Notes

- Penalty shootouts: this resolver only fills the R32 fixtures. The open item you
  flagged, wiring shootout winners before the knockouts, lives downstream of this.
  Knockout matches need a `winner` that falls back to a `pens_winner` column when
  the 90+ET result is level. Add that to the result model that feeds R16; the
  seeding layer here does not touch it.
- Conduct-score data: API-Football’s free tier does not reliably expose per-match
  card counts in a form that reconstructs the FIFA conduct score. The resolver
  defaults `conduct` to 0 and `fifa_rank` to a sentinel, so it degrades to
  points/GD/GF only. That is correct in the vast majority of cases but can mis-rank
  the 8th-vs-9th third-place cutoff when teams are dead level on the top three. If
  you want exact behavior at that boundary, source card data or hardcode the FIFA
  ranking snapshot as a small seed.
- The 8th-place cutoff is the only place a tie actually changes who advances.
  Worth a dbt test that flags when thirds ranked 8 and 9 are equal on points, GD,
  and GF, so you know when the cheaper ranking might diverge from official.
- Coordinate-frame validation for the xG model is a separate workstream and is not
  affected by any of this.

## Validation already done

`annex_c_map.json` was parsed straight from the FIFA PDF and checked:

- exactly 495 combinations, options 1 to 495 all present
- perfect bijection: the 8 group letters in each row equal its combo_key, and the
  set of keys equals C(12,8) exactly
- every slot assignment respects the eligible-thirds sets above (0 violations)
- each group appears in exactly C(11,7) = 330 of the 495 combinations

Run `python3 third_place_seeding.py` to re-run these checks plus the bijection test.