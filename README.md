# leetcode-nagger

A daily cron job that reads my Blind 75 tracker out of Google Sheets and
sends me a Discord nag at 7pm Eastern if I'm behind on cold attempts or
spaced-repetition reviews.

## Why

Because I desperately need someone to tell me to lock in.

But I didn't want to set up another thing to log into... I wanted to keep the tracking in my Google sheet, because I like my Google sheets.


So now:
- A GitHub Actions cron fires once a day.
- The script reads the sheet directly via the Google Sheets API, decides
  whether there's anything to yell at me about, and pushes a notification
  through a Discord webhook.

## How it works

There are two tabs in the same Google Sheet that the bot reads.

The first is my **Blind 75 Tracker** — one row per problem, with columns for
`Problem`, `Diff`, `Cold ✓ (date)`, `1wk Review`, and `3wk Review`. I fill in
those date columns whenever I actually finish a pass. The sheet has a
dashboard at the top with stats and stuff, but the bot just scans past that
until it finds the real header row.

The second is my **Master Schedule** — one row per study week. The columns
the bot cares about are `Dates` (something like `May 20-24`) and `# New`
(just a number — how many new cold attempts I'm planning to do that week).
That `# New` number is what lets me get ahead and shut the bot up early.

Every evening, the bot does this:

1. Figures out which study week today belongs to.
2. Counts how many cold attempts I've already logged this week.
3. Looks for any overdue reviews — a problem with `Cold ✓` set but `1wk
   Review` blank that's more than a week old, or `1wk Review` set but `3wk
   Review` blank that's more than two weeks past the 1wk date.
4. Decides what to do:
   - **If it's Sunday** — no new problems on Sundays. Instead I get a "go
     re-read your notes" reminder listing every problem I've cold-attempted
     so far. Overdue reviews still show up if there are any.
   - **Mon–Sat** — if I've already hit this week's `# New` target, the bot
     doesn't ask for new problems. Otherwise it nags me whenever I haven't
     done a cold attempt yet today. Overdue reviews always fire either way.
   - **First run after hitting quota** — fires a separate, silent (no @-ping)
     "good job" message with the week's streak count. See
     [Weekly congrats](#weekly-congrats) below.
   - **Nothing to do** — quiet day. No Discord ping.

### About the streak

Consecutive completed weeks where I hit the `# New` target. Shown on the
weekly congrats (counting the current week as +1) and on the regular nag's
streak card. Misses a week → resets to 0.

### Weekly congrats

The first time I hit the `# New` target for a week, the next script run
sends a separate Discord message — green embed, no @-ping, randomized
slightly snarky title, streak count, and `cold / target` for the week.
Dedup is handled by a tiny `state.json` at the repo root keyed by the
week's start date, and the GitHub Action commits it back so the bot doesn't
spam me every day after I finish the quota.

### Channels

- **Discord** is the only channel. Posts to a channel I made just for this.
  Nags @-mention me if `DISCORD_USER_ID` is set — that's what triggers the
  push notification. The weekly congrats deliberately *doesn't* mention
  anyone, so it shows up silently without buzzing my phone.

## What the Discord ping looks like

```
@shuang
╭─ LeetCode Nag · Thursday, May 21 ───────────╮
│                                              │
│  New cold attempt pending                    │
│  Do a new cold attempt today.                │
│  2/7 done this week.                         │
│                                              │
│  1 1-week review(s) overdue                  │
│  • Contains Duplicate (Easy) — 3d overdue    │
│                                              │
│  Stop procrastinating.                       │
╰──────────────────────────────────────────────╯
```

The real embed picks one accent color depending on what's worst: red if any
review is overdue, amber if it's just "you didn't do a problem today," blue
on Sundays. The title is a link that opens the tracker tab.

The weekly congrats looks like this — no @-mention at the top, green
accent, randomized title:

```
╭─ Quota met. I'm shocked. Pleasantly shocked. ╮
│                                              │
│  Streak           This week                  │
│  3-week streak.   7/7 done.                  │
│                                              │
│  Don't get cocky.                            │
╰──────────────────────────────────────────────╯
```

## Schedule

GitHub Actions cron only knows UTC and doesn't follow daylight saving, but I
wanted "7pm Eastern" to actually mean 7pm year-round. So the workflow
registers two cron lines (one for EDT, one for EST) and a gate step at the
top of the job checks `TZ=America/New_York date +%H` and exits early on
whichever one isn't in season.

Two things worth knowing about scheduled GitHub Actions runs:

- They can show up 5–15 minutes late if GitHub is busy.
- The schedule pauses if you haven't pushed to the repo in 60 days.

Both are fine for a daily nag.

## Setup

### 1. Create a Google Cloud service account

In Google Cloud Console:

1. Make (or pick) a project, then **enable the Google Sheets API** on it.
2. Go to **IAM & Admin → Service Accounts → Create service account**. Name
   it anything (e.g. `leetcode-nagger`).
3. Open the new service account → **Keys → Add Key → JSON**. Save the
   downloaded JSON file — the whole thing goes into one env var below.
4. Copy the service account's `client_email` (looks like
   `leetcode-nagger@your-project.iam.gserviceaccount.com`).
5. In Google Sheets, open your tracker, click **Share**, paste the
   `client_email`, and give it **Viewer** access.

### 2. Add the `# New` column

If you want the weekly cap, add a column called `# New` (or `LC Target` /
`Target` — the header matcher in `nag.py` is loose) next to your `Dates`
column in the Master Schedule. One integer per week. Blank rows just get
ignored.

### 3. Fill in env vars

Copy `.env.example` to `.env` and fill in your values.

You need: `GOOGLE_SERVICE_ACCOUNT_JSON` (the entire JSON key as a single
string), `SHEET_ID`, `DISCORD_WEBHOOK_URL`.

Optional but useful:

- `SHEET_TAB` — the tracker tab name. Default is the first tab.
- `SCHEDULE_TAB` — the Master Schedule tab name. Leave blank if you don't
  want the weekly cap, and the bot will just nag once a day.
- `DISCORD_USER_ID` — your Discord user ID. That's what makes the message
  actually ping you.

### 4. Run it locally

```sh
pip install -r requirements.txt
python nag.py
```

Exits 0 if everything went fine (or if there was nothing to nag about), 1 if
the Discord post fails.

### 5. Push to GitHub and add the secrets

In your repo: Settings → Secrets and variables → Actions → New repository
secret. One per env var, same names. For `GOOGLE_SERVICE_ACCOUNT_JSON`,
paste the entire contents of the key file. Once they're in, go to the
Actions tab, pick **leetcode-nag**, and hit "Run workflow" to test. The 7pm
gate skips on manual triggers so it fires right away.

## Stack

- Python 3.11 — standard library plus `google-api-python-client`,
  `google-auth`, and `python-dotenv`.
- Google Sheets API (service-account auth) for the tracker reads.
- Plain `urllib` for the Discord webhook (with a custom User-Agent —
  Discord 403s Python's default).
- GitHub Actions for the cron.

## Files

- `nag.py` — everything. One file.
- `.github/workflows/nag.yml` — the cron + gate step, plus a tail step
  that commits `state.json` back when it changes (needs `contents: write`).
- `state.json` — tracks `last_congratulated_week_start` so the congrats
  message only fires once per week. Committed by the workflow.
- `requirements.txt` — three lines.
- `.env` — gitignored.
