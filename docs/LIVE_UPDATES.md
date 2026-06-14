# Live updates: the external refresh pinger

The dashboard refreshes near-live during matches (~5-10 min behind play). The
trigger is **not** GitHub's scheduled cron: GitHub drops high-frequency `*/5`
schedules and lags the rest by hours, so it cannot drive a 5-minute refresh. We
use a free external scheduler to ping GitHub instead.

## How it works

```
cron-job.org (free)  --POST every 5 min-->  GitHub repository_dispatch (type: refresh)
        -> deploy.yml "gate" job: is a match in its live window? (include/schedule_window.py)
              yes -> build live data + redeploy the site
              no  -> skip (the gate job ends in ~20s; nothing is republished)
```

So the ping fires around the clock, but a build only happens during a live match
window (group ~2h30, knockout ~3h45). Off-game pings are a near-instant no-op.
The 6-hour baseline cron still runs for off-game freshness.

## One-time setup (~5 minutes)

### 1. Create a fine-grained personal access token (PAT)

GitHub -> **Settings -> Developer settings -> Personal access tokens ->
Fine-grained tokens -> Generate new token**:

- **Resource owner:** your account
- **Repository access:** Only select repositories -> `worldcup26-elt`
- **Permissions -> Repository permissions -> Contents:** Read and write
  (the `repository_dispatch` endpoint needs Contents write; classic tokens need
  the `repo` scope)
- **Expiration:** your choice (e.g. through Jul 19, 2026)

Copy the token. Treat it like a password; it goes into cron-job.org, not the repo.

### 2. Create the cron-job.org job

Sign up at https://cron-job.org (free) and create a job:

- **URL:** `https://api.github.com/repos/aatrey56/worldcup26-elt/dispatches`
- **Request method:** `POST`
- **Schedule:** every 5 minutes (`*/5`). Optional: restrict to the tournament
  dates / typical match hours to cut down on idle pings.
- **Headers:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer YOUR_PAT_HERE`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `User-Agent: worldcup26-pinger` (GitHub rejects requests with no User-Agent)
- **Request body:** `{"event_type":"refresh"}`

Save and enable it.

### 3. Verify

- A successful ping returns HTTP **204** (no content). cron-job.org will show the
  job as succeeding.
- During a live match, a new **Deploy** run tagged `repository_dispatch` appears
  within ~5 min and republishes. Outside a match window, the run appears but the
  build is skipped (the gate decides `should_build=false`).

## Manual fallback

Any time, you can force a refresh without the pinger:

```
gh workflow run deploy.yml --ref main
```

This always builds (the gate always allows `workflow_dispatch`).

## Notes

- The PAT lives only in cron-job.org, never in the repo. Rotate or delete it when
  the tournament ends.
- The pinger triggers the lightweight `gate` job every 5 min; on a public repo
  GitHub Actions minutes are free, so the idle pings cost nothing but a short run.
- Honest ceiling: even with a reliable ping, the static-site rebuild + GitHub
  Pages republish put freshness at ~5-10 min behind live play. True
  second-by-second would need an always-on server or browser-side polling.
