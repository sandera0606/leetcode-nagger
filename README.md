# leetcode-nagger

A daily cron job that reads my Blind 75 tracker out of Google Sheets and sends
me an email + Discord nag at 7pm Eastern if I'm behind on cold attempts or
spaced-repetition reviews.

## Why

Because I desperately need someone to tell me to lock in.

But I didn't want to set up another thing to log into... I wanted to keep the tracking in my Google sheet, because I like my Google sheets.


So now:
- A GitHub Actions cron fires once a day.
- Composio reads the sheet, and the script decides whether there's anything to yell at me about, and pushes a notification through Gmail and a Discord webhook.

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
     Discord-only "good job" message with the week's streak count. Email
     stays quiet. See [Weekly congrats](#weekly-congrats) below.
   - **Nothing to do** — quiet day. No email, no Discord ping.

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

Email is intentionally *not* sent for this — congratulations don't need to
clutter the inbox, and the no-ping Discord message is just there if I want
to look.

### Channels

- **Email** is always sent for nags. Goes through Composio's Gmail
  connector and shows up as the styled HTML card below. The weekly congrats
  skips email on purpose.
- **Discord** is optional. Posts to a channel I made just for this. Nags
  @-mention me if `DISCORD_USER_ID` is set — that's what triggers the push
  notification. The weekly congrats deliberately *doesn't* mention anyone,
  so it shows up silently without buzzing my phone.
- The two channels are independent. If one fails the other still goes out.

## What the email looks like

A weekday email when I'm behind on cold attempts and have one stale 1-week
review:

```
┌────────────────────────────────────────────────┐
│ LEETCODE NAG                                   │
│ Thursday, May 21, 2026                         │
├────────────────────────────────────────────────┤
│ ▌ Do a new cold attempt today.                 │
│ ▌ 2/7 done this week.                          │
├────────────────────────────────────────────────┤
│ ▌ 1 1-week review(s) overdue                   │
│ ▌                                              │
│ ▌  • Contains Duplicate (Easy) — 3d overdue    │
├────────────────────────────────────────────────┤
│ [ Open Tracker → ]                             │
│                                                │
│ Stop procrastinating.                          │
└────────────────────────────────────────────────┘
```

The real HTML version has colored left borders on each card: amber for "new
cold attempt pending," red for overdue reviews, blue for the Sunday note
reminder. The "Open Tracker" button drops you directly onto the Blind 75 tab
— the bot looks up the tab's `gid` at runtime, so I don't have to hardcode
anything.

A Sunday morning email, when I'm caught up for the week:

```
┌────────────────────────────────────────────────┐
│ LEETCODE NAG                                   │
│ Sunday, May 24, 2026                           │
├────────────────────────────────────────────────┤
│ ▌ It's Sunday. No new problems today.          │
│ ▌ Re-read your notes on the 5 problem(s)       │
│ ▌ you've cold-attempted.                       │
│ ▌                                              │
│ ▌  • Contains Duplicate                        │
│ ▌  • Valid Anagram                             │
│ ▌  • Two Sum                                   │
│ ▌  • Group Anagrams                            │
│ ▌  • Top K Frequent Elements                   │
├────────────────────────────────────────────────┤
│ [ Open Tracker → ]                             │
│                                                │
│ Stop procrastinating.                          │
└────────────────────────────────────────────────┘
```

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

### 1. Connect accounts in Composio

You want the **Developer Platform** side of Composio, not "For You." (The
"For You" side is just for MCP and gives you an API key that doesn't
authenticate the Python SDK — I found this out the hard way.)

Create a project there, then connect:

- Google Sheets, with read access to the tracker.
- Gmail, with permission to send from the account you want the nags to come
  from.

While you're connecting, you'll pick a `user_id` — `default` is fine.

### 2. Add the `# New` column

If you want the weekly cap, add a column called `# New` (or `LC Target` /
`Target` — the header matcher in `nag.py` is loose) next to your `Dates`
column in the Master Schedule. One integer per week. Blank rows just get
ignored.

### 3. Fill in env vars

Copy `.env.example` to `.env` and fill in your values.

You need: `COMPOSIO_API_KEY`, `COMPOSIO_ENTITY_ID`, `SHEET_ID`,
`RECIPIENT_EMAIL`.

Optional but useful:

- `SHEET_TAB` — the tracker tab name. Default is the first tab.
- `SCHEDULE_TAB` — the Master Schedule tab name. Leave blank if you don't
  want the weekly cap, and the bot will just nag once a day.
- `DISCORD_WEBHOOK_URL` and `DISCORD_USER_ID` — webhook and your Discord
  user ID. The user ID is what makes the message actually ping you.

### 4. Run it locally

```sh
pip install -r requirements.txt
python nag.py
```

Exits 0 if everything went fine (or if there was nothing to nag about), 1 if
a channel failed.

### 5. Push to GitHub and add the secrets

In your repo: Settings → Secrets and variables → Actions → New repository
secret. One per env var, same names. Once they're in, go to the Actions tab,
pick **leetcode-nag**, and hit "Run workflow" to test. The 7pm gate skips on
manual triggers so it fires right away.

## Stack

- Python 3.11 — standard library plus `composio` (1.x) and `python-dotenv`.
  That's it.
- Composio for the Google Sheets reads and the Gmail send.
- Plain `urllib` for the Discord webhook (with a custom User-Agent —
  Discord 403s Python's default).
- GitHub Actions for the cron.

## Files

- `nag.py` — everything. One file.
- `.github/workflows/nag.yml` — the cron + gate step, plus a tail step
  that commits `state.json` back when it changes (needs `contents: write`).
- `state.json` — tracks `last_congratulated_week_start` so the congrats
  message only fires once per week. Committed by the workflow.
- `requirements.txt` — two lines.
- `.env` — gitignored.