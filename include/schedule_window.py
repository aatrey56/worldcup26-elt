"""
Schedule-aware live-window gate for the auto-update workflow.

The deploy workflow runs on a frequent cron (every 5 minutes) so the site can
refresh during matches, but rebuilding every 5 minutes around the clock is
wasteful and pointlessly republishes a static site. This gate answers one
question: is any match in its live window RIGHT NOW? If not, the frequent run
skips the build entirely and the published site stays as-is.

A match's live window is [kickoff - PRE, kickoff + duration + POST], where the
duration is generous enough to cover stoppage time, half-time, and (for
knockouts) extra time and penalties, plus a tail so the FINAL score and the
standings settle on the last refresh after full time:
  - group matches:   ~2h of play  -> 150 min window
  - knockout matches: up to ~3h15 incl. extra time + penalties -> 225 min window

Kickoff times in the schedule seed are US Eastern (America/New_York); they are
converted to UTC via zoneinfo so the gate is correct across the EDT span of the
tournament (June-July 2026).

Stdlib only. Run directly to print the decision:
    python -m include.schedule_window
It prints `should_build=true` or `should_build=false` to STDOUT (so a workflow
can do `python -m include.schedule_window >> "$GITHUB_OUTPUT"`) and a
human-readable reason to STDERR.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# minutes before kickoff to start refreshing, and the in-play window length.
PRE_MIN = 5
GROUP_WINDOW_MIN = 150  # ~2h of play + stoppage/half-time + settle tail
KNOCKOUT_WINDOW_MIN = 225  # up to ~3h15 incl. extra time + penalties + settle tail

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEDULE = os.path.join(HERE, "..", "dbt", "seeds", "schedule_seed.csv")


def _kickoff_utc(date_str: str, kickoff_et: str) -> datetime:
    """Combine the seed's date + Eastern kickoff into an aware UTC datetime."""
    naive = datetime.strptime(f"{date_str} {kickoff_et}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=EASTERN).astimezone(UTC)


def live_matches(now: datetime, schedule_path: str = DEFAULT_SCHEDULE) -> list[dict]:
    """Return the schedule rows whose live window contains `now` (UTC)."""
    live = []
    with open(schedule_path, newline="") as f:
        for row in csv.DictReader(f):
            kickoff = _kickoff_utc(row["date"], row["kickoff_et"])
            window = GROUP_WINDOW_MIN if row["stage"] == "group" else KNOCKOUT_WINDOW_MIN
            start = kickoff - timedelta(minutes=PRE_MIN)
            end = kickoff + timedelta(minutes=window)
            if start <= now <= end:
                live.append(row)
    return live


def main() -> None:
    now = datetime.now(UTC)
    live = live_matches(now)
    should_build = bool(live)

    # decision -> stdout (capturable into $GITHUB_OUTPUT)
    print(f"should_build={'true' if should_build else 'false'}")

    # reason -> stderr (shows in the workflow log)
    print(f"[gate] now={now.isoformat()} live_matches={len(live)}", file=sys.stderr)
    for m in live:
        print(
            f"[gate] LIVE window: M{m['match_no']} {m['home_team']} vs {m['away_team']} "
            f"({m['stage']}, kickoff {m['date']} {m['kickoff_et']} ET)",
            file=sys.stderr,
        )
    if not live:
        print(
            "[gate] no match in its live window; frequent run will skip the build",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
