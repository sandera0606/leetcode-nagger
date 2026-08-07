# leetcode-nagger

A cron job that reads your LeetCode tracker out of Google Sheets and nags you
— on Discord, by email, by SMS — when you're behind on new problems or on
spaced-repetition reviews.

You keep your progress in a Google Sheet, which you were going to do anyway.
There is no app to log into, no account to make, and nothing to remember.
Fork this, paste in a few secrets, edit one config file, done.

```
@you
╭─ LeetCode Nag · Thursday, May 21 ────────────╮
│                                              │
│  Streak: 6 day(s). Don't be the reason it    │
│  ends.                                       │
│  6-day streak.                               │
│                                              │
│  Do a new cold attempt today.                │
│  Nothing logged today yet.                   │
│  1 to go · 35 left in Blind 75.              │
│                                              │
│  1 first review(s) overdue                   │
│  • Contains Duplicate (Easy) — 3d overdue    │
│                                              │
│  Stop procrastinating.                       │
╰──────────────────────────────────────────────╯
```

---

## Contents

- [Quick start](#quick-start)
- [The tracker sheet](#the-tracker-sheet)
- [Settings (`config.yml`)](#settings-configyml)
- [Notification channels](#notification-channels)
  - [Discord](#discord)
  - [Email (Gmail)](#email-gmail)
  - [SMS](#sms)
- [Secrets reference](#secrets-reference)
- [Running it on GitHub Actions](#running-it-on-github-actions)
- [How it decides what to say](#how-it-decides-what-to-say)
- [Local development](#local-development)
- [Troubleshooting](#troubleshooting)

---

## Quick start

1. **Fork this repo** (button at the top right).

2. **Make your tracker sheet.** Open one of these and hit **File → Make a
   copy**. That's your tracker — it lands in your own Drive, already filled in
   with the problem list and nothing else.

   | List | Problems | Copy this |
   |---|---|---|
   | Blind 75 | 75 | [Open template →](REPLACE_WITH_YOUR_DRIVE_LINK) |
   | NeetCode 150 | 150 | [Open template →](REPLACE_WITH_YOUR_DRIVE_LINK) |
   | NeetCode 250 | 250 | [Open template →](REPLACE_WITH_YOUR_DRIVE_LINK) |

   Prefer not to use someone else's Drive file? The same sheets are in
   `templates/` as `.xlsx` — upload one to Drive and it converts to a Google
   Sheet, formatting and formulas intact. There's a `.csv` of each too, if you
   'd rather File → Import into a sheet you already have.

   All three use a tab named `Tracker`, which is what `config.yml` expects out
   of the box, so switching lists later doesn't mean reconfiguring anything.

3. **Let the bot read the sheet.** Create a Google Cloud service account, put
   its key JSON in a secret, and share the sheet with its email — full steps
   in [Secrets reference](#secrets-reference).

4. **Pick your channels.** Discord, email, SMS, or all three. Each one needs
   a couple of secrets; see [Notification channels](#notification-channels).

5. **Edit `config.yml`** — how often you want to be nagged, at what time, in
   what timezone. Commit it.

6. **Add your secrets** under Settings → Secrets and variables → Actions, then
   go to the Actions tab, enable workflows, pick **leetcode-nag**, and hit
   **Run workflow** to send yourself a test nag.

That's it. From then on it fires once a day at your chosen hour.

---

## The tracker sheet

One row per problem. The bot only cares about five columns:

| Column | What it's for |
|---|---|
| `Problem` | The name. Shown in the nag. **Required.** |
| `Diff` | Easy/Medium/Hard. Shown in brackets. Optional. |
| `Cold ✓ (date)` | The day you first solved it cold. **Required.** |
| `1wk Review` | The day you did the first review. Optional. |
| `3wk Review` | The day you did the second review. Optional. |

Everything else in the template — pattern, time budget, the NeetCode link,
your notes, a confidence dropdown, the dashboard at the top — is for you. The
bot scrolls past all of it looking for the header row.

The dashboard totals recalculate themselves as you fill rows in, and the
`Confidence` column is a Shaky / OK / Strong dropdown that colours its own
cell red, amber or green. Neither is something the bot reads — they're there
so the sheet is worth opening on its own.

**The only thing you have to do is type a date when you finish a pass.** The
bot derives everything else: what's due, what's overdue, your streak, your
percentage.

Header matching is case-insensitive and fuzzy, so `Cold attempt`,
`First review`, `1 week review` and friends all work if you'd rather rename
things. Dates can be `2026-05-20`, `05/20/2026`, `May 20, 2026` — most
formats Sheets produces are understood.

> **Heads up:** the templates are generated from the public NeetCode problem
> lists, so a handful of problems are LeetCode Premium. The `NeetCode` column
> points at NeetCode, which has free versions of those.

---

## Settings (`config.yml`)

This is the file you edit. It holds behaviour only — nothing secret, nothing
that identifies you, so it's safe to commit in a public fork.

```yaml
list: blind75              # blind75 | neetcode150 | neetcode250

sheet:
  tab: Tracker             # tab name; blank = first tab

schedule:
  cadence: weekdays        # daily | weekdays | no_sundays | custom
  days: [mon, tue, wed, thu, fri]   # only used by cadence: custom
  problems_per_day: 1
  timezone: America/New_York
  nag_hour: 19             # 0–23, local to `timezone`
  rest_day_review: true    # nudge you to re-read notes on non-solve days

review:
  enabled: true
  first_days: 7            # first review due 7 days after the cold attempt
  second_days: 21          # second review due 21 days after the cold attempt

stop_when_complete: true   # go quiet once the whole list is done

channels:
  discord: { enabled: true, mention: true }
  email:   { enabled: false, subject_prefix: "[LeetCode]" }
  sms:     { enabled: false, provider: carrier_gateway, carrier: verizon }
```

### Cadence

| `cadence` | You're expected to solve on |
|---|---|
| `daily` | every day |
| `weekdays` | Mon–Fri |
| `no_sundays` | Mon–Sat |
| `custom` | whatever you list in `days:` |

Days that aren't solve days are **rest days**. On a rest day the bot doesn't
ask for a new problem; if `rest_day_review: true` it reminds you to re-read
your notes instead. Overdue reviews get through on any day.

`problems_per_day` raises the bar: set it to `2` and a day only counts once
two cold attempts are logged with that date.

### Timing

`nag_hour` is in `timezone`, and daylight saving is handled for you — set
`19` and it stays 7pm in July and in January. The workflow wakes up hourly and
skips the 23 runs that aren't your hour.

### Reviews

`first_days` counts from the cold attempt. `second_days` also counts from the
cold attempt, but the clock only starts once you've actually logged the first
review — so falling behind pushes the second one back rather than dumping both
on you at once. Set `enabled: false` to turn review nagging off entirely.

### Stopping

With `stop_when_complete: true`, once every problem has a cold date and every
review is logged you get one final congratulations and then silence. Set it
to `false` to keep the review nagging going forever.

---

## Notification channels

Turn on as many as you like in `config.yml`. Each sends independently — a
broken SMS gateway won't cost you the Discord ping.

### Discord

Best signal-to-noise: a rich embed, colour-coded by urgency (red = overdue,
amber = new problem due, blue = rest day, green = celebration).

1. Make a server, or use one you're in. Make a channel just for this.
2. Channel Settings → **Integrations → Webhooks → New Webhook → Copy Webhook
   URL** → that's `DISCORD_WEBHOOK_URL`.
3. Optional but recommended: User Settings → Advanced → **Developer Mode** on,
   then right-click yourself → **Copy User ID** → that's `DISCORD_USER_ID`.
   Nags @-mention you, which is what actually triggers a phone notification.
   Celebrations never mention anyone, so they arrive quietly.

### Email (Gmail)

Sends a formatted HTML email (with a plain-text fallback).

1. Turn on **2-Step Verification** on the Google account you're sending from.
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   and create an app password. That 16-character string is
   `GMAIL_APP_PASSWORD` — **not** your normal password, which won't work.
3. Set `GMAIL_ADDRESS` (the account it's sent *from*) and `EMAIL_TO` (where it
   goes; comma-separate for several).

Not a Gmail user? Set `SMTP_HOST` and `SMTP_PORT` to your provider's server —
ports 587 (STARTTLS) and 465 (SSL) are both handled — and put your username
and password in `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` anyway.

### SMS

A single short line: what's due, your progress, your streak. Two ways to send it.

**`provider: carrier_gateway`** — free. Most North American carriers turn an
email to `5551234567@gateway` into a text. It reuses the Gmail credentials
above, so set those up first. Set `carrier:` to one of:

| | |
|---|---|
| **US** | `att` `boost` `cricket` `googlefi` `metropcs` `mint` `sprint` `tmobile` `uscellular` `verizon` `visible` `xfinity` |
| **Canada** | `bell` `fido` `freedom` `koodo` `rogers` `telus` `virgin` |

Delivery is best-effort and unmetered, and some carriers have quietly retired
their gateway. If texts stop showing up, switch to Twilio.

**`provider: twilio`** — paid, but reliable and works worldwide. Get an
account, buy a number, then set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and
`TWILIO_FROM`.

Either way, `SMS_TO` is your number.

---

## Secrets reference

Locally these go in `.env` (copy `.env.example`, it's gitignored). On GitHub
they go in **Settings → Secrets and variables → Actions → New repository
secret**, one per name. Same names in both places.

| Secret | Needed for | What it is |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | always | The whole service-account key file, pasted as one value |
| `SHEET_ID` | always | The long id in your sheet's URL, between `/d/` and `/edit` |
| `DISCORD_WEBHOOK_URL` | Discord | Channel Settings → Integrations → Webhooks |
| `DISCORD_USER_ID` | Discord | Your user id, so nags ping you |
| `GMAIL_ADDRESS` | email, SMS gateway | The account nags are sent *from* |
| `GMAIL_APP_PASSWORD` | email, SMS gateway | A Google App Password |
| `EMAIL_TO` | email | Where nags go |
| `SMTP_HOST`, `SMTP_PORT` | non-Gmail SMTP | Defaults to `smtp.gmail.com:587` |
| `SMS_TO` | SMS | Your mobile number |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | Twilio SMS | From the Twilio console |

### Getting `GOOGLE_SERVICE_ACCOUNT_JSON`

The bot reads your sheet as a robot user, so you never hand it your Google
password.

1. In [Google Cloud Console](https://console.cloud.google.com), create (or
   pick) a project, then **enable the Google Sheets API** on it.
2. **IAM & Admin → Service Accounts → Create service account.** Name it
   anything. No roles needed.
3. Open it → **Keys → Add Key → Create new key → JSON.** A file downloads.
4. Paste the **entire file contents**, braces included, as the value of the
   `GOOGLE_SERVICE_ACCOUNT_JSON` secret.
5. Copy the service account's `client_email` (it looks like
   `something@your-project.iam.gserviceaccount.com`), then in your sheet click
   **Share**, paste it, and give it **Viewer**. Without this step the bot gets
   a 403 — the key alone doesn't grant access to your sheet.

---

## Running it on GitHub Actions

`.github/workflows/nag.yml` runs hourly and exits in about five seconds on the
23 runs that aren't your `nag_hour`. You don't need to touch the cron line to
change the time — that's what `config.yml` is for.

Two things to know about scheduled Actions:

- Runs can land 5–15 minutes late when GitHub is busy.
- **The schedule pauses after 60 days with no pushes to the repo.** The bot
  commits `state.json` back on days it sends something, which usually keeps
  the clock alive on its own.

Public repos get unlimited Actions minutes. Private forks burn roughly 6
minutes a day against the free 2,000/month, which is comfortably fine.

`workflow_dispatch` is enabled, so **Run workflow** sends immediately
regardless of the hour — that's your test button.

---

## How it decides what to say

Every run:

1. Reads every row under the header.
2. Counts cold attempts dated today, and problems still without a cold date.
3. Finds overdue reviews — a `Cold ✓` with no first review older than
   `first_days`, or a first review with no second review older than
   `second_days - first_days`.
4. Computes the streak: consecutive **solve days**, walking backwards, where
   you logged at least `problems_per_day`. Rest days are skipped, not broken.
   Today doesn't count against you until you've done it.
5. Sends at most one nag per day, containing whichever of these apply:
   - **new problem due** — a solve day, quota not met, problems remaining
   - **overdue reviews** — always, any day
   - **rest day nudge** — re-read your notes on what you've solved so far
   - nothing applies → nothing is sent. Quiet days are the point.

Separately, and silently (no @-mention), it celebrates at 25%, 50% and 75% of
the list, and once more when you finish it. Those fire once each; `state.json`
remembers which have gone out.

---

## Local development

```sh
pip install -r requirements.txt
cp .env.example .env      # then fill it in

python nag.py --dry-run --force   # print what it would send, send nothing
python nag.py --test              # actually send, even if nothing is due
python nag.py --force             # normal run, ignoring the hour gate
python nag.py                     # exactly what the cron does
```

`--dry-run` is the fastest way to check your sheet parses. `--test` is the
fastest way to check your channel credentials work.

Exit code is 0 when everything sent (or there was nothing to send), 1 when an
enabled and configured channel failed.

Tests — no network, no credentials needed:

```sh
python -m unittest discover tests
```

Regenerating the templates, if you ever want to (needs
`pip install -r requirements-dev.txt`):

```sh
python tools/build_problem_data.py      # refresh data/problems.json upstream
python tools/make_template.py --all     # rebuild templates/
```

---

## Troubleshooting

**"Couldn't find the tracker header row"** — `sheet.tab` in `config.yml`
doesn't match your tab name, or the tab has no `Problem` + `Cold` columns.
Tab names are case- and space-sensitive.

**403 from Google** — you didn't share the sheet with the service account's
`client_email`, or the Sheets API isn't enabled on the project.

**Discord 403** — the webhook URL is wrong or the webhook was deleted.

**Gmail "Username and Password not accepted"** — you used your account
password instead of an App Password, or 2-Step Verification isn't on.

**No SMS arriving** — carrier gateways fail silently. Confirm the email
channel works first (same credentials), check the carrier is right, then
switch to Twilio if it still doesn't land.

**Nothing happens at all** — check the Actions tab. Forks have workflows
disabled until you click through the banner enabling them, and scheduled runs
pause after 60 days of no pushes.

**It nagged and I'd already done the work** — you logged the date in the wrong
column, or in a format that didn't parse. Run `python nag.py --dry-run
--force` and check the counts on the first line of output.

---

## Files

```
nag.py                  entry point — gate, orchestration, exit codes
config.yml              your settings
nagger/
  config.py             loads and validates config.yml
  sheets.py             Google Sheets reads
  tracker.py            parses rows; works out what's due, overdue, streak
  messages.py           copy pools; builds the channel-agnostic report
  state.py              once-a-day and once-per-milestone dedup
  notify/               discord.py · mail.py · sms.py
data/problems.json      the three problem lists, merged
templates/              blank tracker sheets, .xlsx and .csv
tools/                  regenerate the data and the templates
tests/                  offline tests
```

## Credits

Problem lists come from [NeetCode](https://neetcode.io) — the `blind75` and
`neetcode150` membership flags from
[neetcode-gh/leetcode](https://github.com/neetcode-gh/leetcode), and the
NeetCode 250 roadmap via
[ascherj/neetcode-250-guide](https://github.com/ascherj/neetcode-250-guide).

MIT licensed. Fork it, change the insults, make it yours.
