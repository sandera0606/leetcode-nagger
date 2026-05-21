# leetcode-nagger

A daily cron job that checks a Google Sheet of scheduled LeetCode problems and
yells at me if today's problem isn't done yet.

- **Source of truth:** Google Sheet with columns `scheduled_date`, `problem`,
  `difficulty`, `date_completed`. Header row must contain those exact names
  (case-insensitive, extra columns OK).
- **Read access:** Composio Google Sheets connector.
- **Nag channels:** Gmail via Composio (required). Twilio SMS via Composio and
  Discord via a plain webhook are both **optional** — leave their env vars
  blank to skip them.
- **Scheduler:** GitHub Actions cron — no server to maintain.

## How it works

`nag.py` runs once per workflow trigger:

1. Pull every row from the configured sheet (and tab) via Composio's
   `GOOGLESHEETS_BATCH_GET`.
2. Find the row whose `scheduled_date` matches today.
3. If no row matches → exit quietly.
4. If `date_completed` already contains today → exit quietly.
5. Otherwise, send a nag through every configured channel. Email always runs;
   SMS and Discord are skipped if their env vars are blank. Each channel is
   sent independently — a failure in one doesn't stop the others.

Dates in `scheduled_date` and `date_completed` are parsed flexibly — `YYYY-MM-DD`,
`MM/DD/YYYY`, `MM/DD/YY`, `DD/MM/YYYY`, and `YYYY/MM/DD` all work. If parsing
fails, the script falls back to a substring match on `YYYY-MM-DD`.

## Setup

### 1. Connect accounts in Composio

In your Composio dashboard, connect (for the same entity / user ID):

- **Google Sheets** — give it read access to the sheet you'll use. *(required)*
- **Gmail** — give it send permission for the account you want nags sent from.
  *(required)*
- **Twilio** — paste in your Twilio account SID and auth token. *(optional —
  skip if you don't want SMS nags)*

Note your **entity ID** (often `default` if you only have one user).

### 2. Fork / clone this repo into GitHub

GitHub Actions will run the workflow from there.

### 3. Add GitHub Secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

**Required:**

| Secret | What it is |
| --- | --- |
| `COMPOSIO_API_KEY` | Consumer API key from your Composio dashboard. |
| `COMPOSIO_ENTITY_ID` | The Composio user/entity ID that owns the connections (often `default`). |
| `SHEET_ID` | The Google Sheet ID — the long string between `/d/` and `/edit` in the sheet URL. |
| `RECIPIENT_EMAIL` | Address to send the nag email to. |

**Optional** (leave blank or omit the secret to skip that channel):

| Secret | What it is |
| --- | --- |
| `SHEET_TAB` | Name of the tab within the spreadsheet (e.g. `Blind 75 Tracker`). Defaults to the first tab. |
| `TWILIO_TO_NUMBER` | Your phone, E.164 format (e.g. `+15551234567`). Both Twilio vars must be set for SMS to send. |
| `TWILIO_FROM_NUMBER` | The Twilio number nags are sent from, E.164 format. |
| `DISCORD_WEBHOOK_URL` | A Discord channel webhook URL (Channel → Edit → Integrations → Webhooks). |

### 4. Adjust the schedule (optional)

Edit the `cron:` line in `.github/workflows/nag.yml`. GitHub Actions cron runs
in **UTC** and does not follow daylight saving. The default `0 0 * * *` fires
at 00:00 UTC every day, which is:

- 7pm US Eastern (8pm during daylight saving)
- 4pm US Pacific (5pm during daylight saving)

Pick a time after you'd realistically have finished the day's problem.

> Heads up: GitHub Actions scheduled workflows can be delayed by 15+ minutes
> during peak load, and the schedule pauses if no commits are pushed for 60
> days. For a daily nag, both are fine.

### 5. Test it

In the Actions tab, pick **leetcode-nag** → **Run workflow** to fire it
manually. Watch the run logs.

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

The script exits 0 on success or when there's nothing to nag about, and exits 1
if one or more channels failed.

## Troubleshooting

- **`Sheet header missing required columns`** — your header row doesn't have
  one of `scheduled_date`, `problem`, `difficulty`, `date_completed`. Rename
  them and re-run.
- **`No problem scheduled for <date>`** — no row has today's date in
  `scheduled_date`. Either you legitimately have nothing scheduled, or your
  date format isn't being parsed; add today's date as `YYYY-MM-DD` to confirm.
- **Composio action name errors** — if Composio renames `GOOGLESHEETS_BATCH_GET`,
  `GMAIL_SEND_EMAIL`, or `TWILIO_SEND_AN_SMS_MESSAGE`, update the `Action.*`
  references in `nag.py`. Run `composio actions --app gmail` (etc.) to list the
  current names.
- **One channel keeps failing** — the other two still send. Check the GitHub
  Actions log for the stderr line starting with `FAILED <channel>`.
