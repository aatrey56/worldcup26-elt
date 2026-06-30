---
title: Knockout Bracket
---

The knockout phase runs from the round of 32 through to the final on July 19, 2026 at MetLife Stadium. With 48 teams, 2026 introduces a round of 32 for the first time.

This bracket is **live and projected**. The Round of 32 is filled in right now from the current group standings *as things stand* (using FIFA's official third-place seeding rules), so you can see who would play whom if the groups ended this minute. Each team carries its group-position tag (for example `[1A]` for the winner of Group A, `[3C]` for the third-placed side of Group C). A `(!)` next to a team means its group position is **mathematically clinched** (locked: no completion of the remaining group games can change it, including positions already settled by head-to-head); `(proj)` means it is **projected** from the current table and can still shift. Once a knockout game is played, the real score and the advancing team replace the projection. The Round of 16 onward stays on placeholders until its feeder games are decided.

```sql bracket
select
  match_no,
  stage,
  round_label,
  -- format the DATE to a fixed string here. If passed through as a raw DATE,
  -- Evidence loads it as a JS Date at UTC midnight, which a browser in a
  -- behind-UTC timezone (e.g. US Eastern) renders as the PREVIOUS day. The
  -- kickoff times are already stored in ET, so we present the ET calendar date.
  strftime(match_date, '%a %b %-d') as match_date,
  kickoff_et,
  channel_en,
  channel_es,
  venue,
  home_label,
  away_label,
  home_seed,
  away_seed,
  home_clinched,
  away_clinched,
  -- cast scores to int: Evidence stores the nullable score columns as float in
  -- the parquet, so rendering them directly would show "2.0".
  case when home_score is not null then cast(home_score as int) end as home_score,
  case when away_score is not null then cast(away_score as int) end as away_score,
  -- penalty-shootout scores (cast to int; null unless the game went to a
  -- shootout). Shown in parentheses next to the full-time score, e.g. "1 (4)".
  case when home_pens is not null then cast(home_pens as int) end as home_pens,
  case when away_pens is not null then cast(away_pens as int) end as away_pens,
  winner_label,
  is_projected,
  is_provisional,
  -- a match is decided once a winner is resolved from a finished result.
  (winner_label is not null) as is_decided
from warehouse.fct_bracket
order by match_no
```

```sql bracket_rounds
select
  stage,
  round_label,
  min(match_no) as first_match,
  count(*) as n_matches
from warehouse.fct_bracket
-- the third-place play-off sits outside the main winners' tree; shown separately
where stage != 'third'
group by stage, round_label
order by first_match
```

```sql third_place
select
  match_no,
  round_label,
  -- formatted as a fixed string to avoid a UTC-midnight DATE rendering as the
  -- previous day in behind-UTC browsers (see the bracket query above).
  strftime(match_date, '%a %b %-d') as match_date,
  venue,
  channel_en,
  channel_es,
  home_label,
  away_label,
  case when home_score is not null then cast(home_score as int) end as home_score,
  case when away_score is not null then cast(away_score as int) end as away_score,
  case when home_pens is not null then cast(home_pens as int) end as home_pens,
  case when away_pens is not null then cast(away_pens as int) end as away_pens,
  winner_label
from warehouse.fct_bracket
where stage = 'third'
```

<style>
  .bracket-scroll {
    overflow-x: auto;
    padding-bottom: 0.75rem;
    -webkit-overflow-scrolling: touch;
  }
  .bracket {
    display: flex;
    gap: 1.75rem;
    align-items: stretch;
    min-width: max-content;
    padding: 0.5rem 0.25rem;
  }
  .bracket-col {
    display: flex;
    flex-direction: column;
    justify-content: space-around;
    gap: 0.6rem;
    min-width: 200px;
  }
  .col-head {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--grey-500, #6b7280);
    text-align: center;
    margin-bottom: 0.25rem;
  }
  .match {
    border: 1px solid var(--grey-200, #e5e7eb);
    border-radius: 8px;
    background: var(--base-100, #ffffff);
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    overflow: hidden;
    transition: box-shadow 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  }
  .match:hover {
    border-color: #2563eb;
    box-shadow: 0 4px 12px rgba(37,99,235,0.16);
    transform: translateY(-1px);
  }
  .match > summary {
    list-style: none;
    cursor: pointer;
    padding: 0;
  }
  .match > summary::-webkit-details-marker { display: none; }
  .team {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.42rem 0.6rem;
    font-size: 0.86rem;
  }
  .team + .team { border-top: 1px dashed var(--grey-200, #e5e7eb); }
  .team-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .team.win .team-name { font-weight: 700; }
  .team.lose { color: var(--grey-400, #9ca3af); }
  .seed-tag {
    font-size: 0.66rem;
    font-weight: 600;
    color: var(--grey-500, #6b7280);
    background: var(--grey-100, #f3f4f6);
    border-radius: 4px;
    padding: 0.05rem 0.3rem;
  }
  .score { font-variant-numeric: tabular-nums; font-weight: 700; min-width: 1ch; text-align: right; }
  .pens { font-weight: 600; font-size: 0.74rem; color: var(--grey-500, #6b7280); margin-left: 0.15rem; }
  .marker { font-size: 0.7rem; font-weight: 700; }
  .marker.clinched { color: #16a34a; }
  .marker.proj { color: #9ca3af; font-weight: 500; }
  .win-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #16a34a; flex: 0 0 auto;
  }
  .win-dot.placeholder { background: transparent; }
  .match-meta {
    padding: 0.45rem 0.6rem;
    border-top: 1px solid var(--grey-200, #e5e7eb);
    background: var(--grey-50, #f9fafb);
    font-size: 0.72rem;
    color: var(--grey-600, #4b5563);
    line-height: 1.4;
  }
  .match-meta .row { display: flex; gap: 0.4rem; }
  .match-meta .lbl { color: var(--grey-400, #9ca3af); min-width: 3.4rem; }
  .match-no { font-size: 0.66rem; color: var(--grey-400, #9ca3af); padding: 0.25rem 0.6rem 0; }
  .legend {
    display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.76rem;
    color: var(--grey-600, #4b5563); margin: 0.25rem 0 0.75rem;
  }
  .legend .marker.clinched, .legend .marker.proj { margin-right: 0.25rem; }
  @media (prefers-color-scheme: dark) {
    .match { background: #1f2937; border-color: #374151; }
    .match-meta { background: #111827; border-color: #374151; }
    .seed-tag { background: #374151; color: #d1d5db; }
  }
</style>

{#if bracket.length > 0}

<div class="legend">
  <span><span class="marker clinched">(!)</span>group position clinched (locked)</span>
  <span><span class="marker proj">(proj)</span>projected from current standings</span>
  <span><span class="seed-tag">1A</span> group-position seed</span>
</div>

<div class="bracket-scroll">
  <div class="bracket">
    {#each bracket_rounds as r}
      <div class="bracket-col">
        <div class="col-head">{r.round_label}</div>
        {#each bracket.filter(d => d.stage === r.stage) as m}
          <details class="match">
            <summary>
              <div class="match-no">Match {m.match_no}</div>
              <div class="team {m.is_decided ? (m.winner_label === m.home_label ? 'win' : 'lose') : ''}">
                <span class="win-dot {m.is_decided && m.winner_label === m.home_label ? '' : 'placeholder'}"></span>
                <span class="team-name">{m.home_label}</span>
                {#if m.home_seed}<span class="seed-tag">{m.home_seed}</span>{/if}
                {#if !m.is_decided && m.is_projected}
                  {#if m.home_clinched}<span class="marker clinched">(!)</span>{:else}<span class="marker proj">(proj)</span>{/if}
                {/if}
                {#if m.is_decided}<span class="score">{m.home_score}{#if m.home_pens !== null && m.home_pens !== undefined}<span class="pens">({m.home_pens})</span>{/if}</span>{/if}
              </div>
              <div class="team {m.is_decided ? (m.winner_label === m.away_label ? 'win' : 'lose') : ''}">
                <span class="win-dot {m.is_decided && m.winner_label === m.away_label ? '' : 'placeholder'}"></span>
                <span class="team-name">{m.away_label}</span>
                {#if m.away_seed}<span class="seed-tag">{m.away_seed}</span>{/if}
                {#if !m.is_decided && m.is_projected}
                  {#if m.away_clinched}<span class="marker clinched">(!)</span>{:else}<span class="marker proj">(proj)</span>{/if}
                {/if}
                {#if m.is_decided}<span class="score">{m.away_score}{#if m.away_pens !== null && m.away_pens !== undefined}<span class="pens">({m.away_pens})</span>{/if}</span>{/if}
              </div>
            </summary>
            <div class="match-meta">
              <div class="row"><span class="lbl">Date</span><span>{m.match_date} {m.kickoff_et}</span></div>
              <div class="row"><span class="lbl">Venue</span><span>{m.venue}</span></div>
              <div class="row"><span class="lbl">TV (EN)</span><span>{m.channel_en}</span></div>
              <div class="row"><span class="lbl">TV (ES)</span><span>{m.channel_es}</span></div>
            </div>
          </details>
        {/each}
      </div>
    {/each}
  </div>
</div>

{#if third_place.length > 0}

## Third-place play-off

<div class="bracket-scroll">
  <div class="bracket">
    {#each third_place as m}
      <div class="bracket-col">
        <div class="col-head">{m.round_label}</div>
        <details class="match">
          <summary>
            <div class="match-no">Match {m.match_no}</div>
            <div class="team {m.winner_label ? (m.winner_label === m.home_label ? 'win' : 'lose') : ''}">
              <span class="win-dot {m.winner_label && m.winner_label === m.home_label ? '' : 'placeholder'}"></span>
              <span class="team-name">{m.home_label}</span>
              {#if m.winner_label}<span class="score">{m.home_score}{#if m.home_pens !== null && m.home_pens !== undefined}<span class="pens">({m.home_pens})</span>{/if}</span>{/if}
            </div>
            <div class="team {m.winner_label ? (m.winner_label === m.away_label ? 'win' : 'lose') : ''}">
              <span class="win-dot {m.winner_label && m.winner_label === m.away_label ? '' : 'placeholder'}"></span>
              <span class="team-name">{m.away_label}</span>
              {#if m.winner_label}<span class="score">{m.away_score}{#if m.away_pens !== null && m.away_pens !== undefined}<span class="pens">({m.away_pens})</span>{/if}</span>{/if}
            </div>
          </summary>
          <div class="match-meta">
            <div class="row"><span class="lbl">Date</span><span>{m.match_date}</span></div>
            <div class="row"><span class="lbl">Venue</span><span>{m.venue}</span></div>
            <div class="row"><span class="lbl">TV (EN)</span><span>{m.channel_en}</span></div>
            <div class="row"><span class="lbl">TV (ES)</span><span>{m.channel_es}</span></div>
          </div>
        </details>
      </div>
    {/each}
  </div>
</div>

{/if}

Click any match to see its date, venue, and TV listings. The bracket scrolls sideways on narrow screens. A score shown as `1 (4)` means the game finished level and was decided on penalties (the number in parentheses is that team's shootout score), and the advancing side is highlighted.

{:else}

The knockout fixtures are not loaded yet. They will appear here as the bracket structure is built.

{/if}

---

_Data: FIFA (api.fifa.com) and football-data.org. xG is a custom model; not affiliated with FIFA._
