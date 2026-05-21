# leetcode-nagger

A daily cron job that reads my Blind 75 tracker + weekly study schedule from
Google Sheets and yells at me through email (+ optionally Discord) if I'm
falling behind on cold attempts or spaced-repetition reviews.

- **Source of truth:** one Google Sheet, two tabs.
  1. **Blind 75 Tracker** — one row per problem with columns `Problem`,
     `Diff` (or `Difficulty`), `Cold ✓ (date)`, `1wk Review`, `3wk Review`.
     The bot scans down from the top until it finds the real header row, so
     dashboard / metadata rows above it are fine.
  2. **Master Schedule** *(optional)* — one row per study week with columns
     `Dates` (e.g. `May 20-24` or `June 29-Jul 3`) and `# New` (a number — how
     many new cold attempts you plan that week). Use this to cap the daily
     nag: once you've hit the week's `# New` target, the bot stops asking for
     more new problems.
- **Read access:** Composio Google Sheets connector (one connection, both tabs).
- **Nag channels:** Gmail via Composio (required). Discord via a plain webhook
  is **optional** — leave its env var blank to skip.
- **Scheduler:** GitHub Actions cron — no server to maintain.

## What the nag actually says

Each run:

1. Fetches both tabs and figures out the current week from `Master Schedule`
   (latest row whose start date is on or before today).
2. Builds a list of:
   - **Overdue 1-week reviews** — rows where `Cold ✓ (date)` is set, `1wk
     Review` is blank, and today ≥ cold_date + 7 days.
   - **Overdue 3-week reviews** — rows where `1wk Review` is set, `3wk
     Review` is blank, and today ≥ 1wk_date + 14 days.
   - **Cold attempts this week** — count of rows where `Cold ✓ (date)` falls
     between the current week's start and today.
3. Decides what to send:
   - **Sunday:** always nags, but swaps the new-problem ask for a "re-read
     your notes on these problems" reminder listing every problem you've
     cold-attempted. Overdue reviews still listed if any.
   - **Mon–Sat:** nags if there are overdue reviews **or** the week's `# New`
     target hasn't been met **and** no cold attempt is logged for today.
     Otherwise silent.
4. Sends through every configured channel. Email always runs; Discord is
   skipped when its env var is blank. Each channel is independent — a failure
   in one doesn't stop the others.

Dates in tracker cells are parsed flexibly (`YYYY-MM-DD`, `MM/DD/YYYY`,
`MM/DD/YY`, `DD/MM/YYYY`, `YYYY/MM/DD`). The schedule's `Dates` column accepts
single-month (`May 20-24`) and cross-month (`June 29-Jul 3`) ranges; year is
inferred from today.

## Setup

### 1. Connect accounts in Composio

In your Composio dashboard, connect (for the same entity / user ID):

- **Google Sheets** — give it read access to the sheet. *(required)*
- **Gmail** — give it send permission for the account that should send nags.
  *(required)*

Note your **entity ID** (usually `default` unless you've created multiple
users).

### 2. Add the `# New` column to your Master Schedule

If you're using the optional weekly cap: add a column literally named `# New`
(or `LC Target`, `Target`, etc. — see header-matching list in `nag.py`) next
to your existing `Dates` column. One integer per week. Leave it blank for
weeks you want the bot to ignore — those rows just won't constrain the daily
nag.

### 3. Fork / clone this repo into GitHub

GitHub Actions will run the workflow from there.

### 4. Add GitHub Secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

**Required:**

| Secret | What it is |
| --- | --- |
| `COMPOSIO_API_KEY` | Consumer API key from your Composio dashboard. |
| `COMPOSIO_ENTITY_ID` | The Composio user/entity ID (usually `default`). |
| `SHEET_ID` | Google Sheet ID — the long string between `/d/` and `/edit`. |
| `RECIPIENT_EMAIL` | Address to send the nag email to. |

**Optional** (leave blank to skip):

| Secret | What it is |
| --- | --- |
| `SHEET_TAB` | Tracker tab name (e.g. `Blind 75 Tracker`). Defaults to first tab. |
| `SCHEDULE_TAB` | Master Schedule tab name. Omit to disable weekly cap — bot then nags daily until you've done a cold attempt that day. |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook (Channel → Edit → Integrations → Webhooks). |
| `DISCORD_USER_ID` | Your Discord user ID. Set this and the Discord nag will `@`-mention you so you actually get a push notification. User Settings → Advanced → toggle **Developer Mode** ON, then right-click your name → **Copy User ID**. |

### 5. Adjust the schedule (optional)

Edit the `cron:` lines in `.github/workflows/nag.yml`. The workflow ships with
two crons (one for EDT, one for EST) and a gate step that exits in the wrong
season, so it fires at **7pm America/New_York year-round** even though GitHub
Actions cron is UTC-only.

To retune to a different local time:

- Pick your target local time during DST (summer).
- Convert to UTC for **both** offsets (UTC−5 standard / UTC−4 daylight in
  Eastern; adjust for other zones).
- Update both cron lines and the `hour=$(TZ=... date +%H)` value in the gate
  step.

> Heads up: scheduled workflows can be delayed 5–15 minutes during GitHub's
> peak load, and pause entirely if no commits land for 60 days. For a daily
> nag, both are fine.

### 6. Test it

In the Actions tab, pick **leetcode-nag** → **Run workflow** to fire it
manually. The gate step skips its 7pm check on manual runs, so it'll execute
immediately. Watch the logs.

## Local dev

```sh
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
python nag.py
```

`nag.py` calls `load_dotenv()` at startup, so any `.env` in the working
directory is loaded automatically. `.env` is gitignored — never commit it.
In CI, `load_dotenv()` is a no-op (no file present); GitHub Actions injects
the real values via `secrets.*`.

The script exits 0 on success or when there's nothing to nag about, and exits
1 if one or more channels failed.

## Troubleshooting

- **`Couldn't find tracker header`** — the tracker tab doesn't contain a row
  with columns `Problem`, `Diff`/`Difficulty`, `Cold ✓ (date)`, `1wk Review`,
  `3wk Review`. Header matching is case-insensitive and tolerates extra
  whitespace, but the column names need to be close to those strings.
- **Master Schedule header not found** — the schedule tab needs a `Dates`
  column and a numeric target column (`# New`, `LC Target`, `Target`, or
  `Leetcode Target`). Without both, the bot still runs but falls back to the
  no-weekly-cap behavior.
- **Schedule `Dates` row not matching today** — the parser accepts `May
  20-24` or `June 29-Jul 3` only. Other formats are skipped silently.
- **Composio action name errors** — if Composio renames
  `GOOGLESHEETS_BATCH_GET` or `GMAIL_SEND_EMAIL`, update the `slug=`
  references in `nag.py`. Run `composio actions --app gmail` (etc.) to list
  current names.
- **One channel keeps failing** — the others still send. Check the GitHub
  Actions log for the stderr line starting with `FAILED <channel>`.
