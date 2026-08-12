# leetcode-nagger

A cron job that reads your LeetCode tracker out of a Google Sheet and nags you
on Discord or by email when you're behind on new problems or on
spaced-repetition reviews.

There's no app to log into and no account to make. You fork it, paste in a few
secrets, and edit one config file.

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

## Setup

Budget about 15 minutes. Most of that is making a Google service account.

### 1. Fork this repo

The button is at the top right.

### 2. Copy a tracker sheet

Open one of these and hit **File → Make a copy**. You get a copy in your own
Drive with the problem list filled in and nothing else.

**→ [Google Sheets templates (Drive folder)](https://drive.google.com/drive/folders/1Nq8qU5llJRm0csHdbn77E94ya2Y4G1ma?usp=sharing)**

| List | Problems | Good for |
|---|---|---|
| Blind 75 | 75 | The classic starting point, about 3 months at 1/weekday. |
| NeetCode 150 | 150 | Blind 75 plus the gaps it leaves. |
| NeetCode 250 | 250 | Everything in the 150, plus 100 more. |

All three use a tab named `Tracker`, which is what `config.yml` expects out of
the box, so switching lists later doesn't mean reconfiguring anything.

<details>
<summary><b>Rather not touch someone else's Drive?</b></summary>

`templates/` has the same sheets as `.xlsx`. Upload one to Drive and it
converts to a Google Sheet with formatting and formulas intact. There's a `.csv`
of each too, if you'd rather **File → Import** into a sheet you already have.
</details>

<details>
<summary><b>Using your own sheet instead?</b> The four columns it needs</summary>

One row per problem. The bot only cares about five columns, four of which are
required. They can be empty, but they have to exist:

| Column | What it's for |
|---|---|
| `Problem` | The name. Shown in the nag. **Required.** |
| `Cold ✓ (date)` | The day you first solved it cold. **Required.** |
| `1wk Review` | The day you did the first review. **Required.** |
| `3wk Review` | The day you did the second review. **Required.** |
| `Diff` | Easy/Medium/Hard. Shown in brackets. Optional. |

The two review columns are how the bot knows a review is outstanding, so a
sheet without them can't be nagged about spaced repetition at all. If one is
missing, the bot stops on the first run and tells you which one, instead of
silently never mentioning reviews.

Header matching is case-insensitive and fuzzy, so `Cold attempt`,
`First review` and `1 week review` all work. Dates can be `2026-05-20`,
`05/20/2026`, or `May 20, 2026`; most formats Sheets produces are understood.

Everything else in the template (pattern, time budget, NeetCode link, notes,
the confidence dropdown, the dashboard at the top) is there for you rather than
for the bot, which scrolls past all of it looking for the header row.
</details>

### 3. Let the bot read the sheet

It reads through a service account, so you never hand it your Google password.

<details>
<summary><b>Creating the service account</b> (the fiddly part, about 5 minutes)</summary>

1. In [Google Cloud Console](https://console.cloud.google.com), create (or
   pick) a project, then **enable the Google Sheets API** on it.
2. **IAM & Admin → Service Accounts → Create service account.** Name it
   anything. No roles needed.
3. Open it → **Keys → Add Key → Create new key → JSON.** A file downloads.
4. That whole file, braces included, is the value of
   `GOOGLE_SERVICE_ACCOUNT_JSON`. In GitHub Secrets, paste it raw. In a local
   `.env` it spans several lines, so it **must** be wrapped in single quotes.
   Without them only the first line is read and you get a half-loaded
   credential:

   ```sh
   GOOGLE_SERVICE_ACCOUNT_JSON='{
     "type": "service_account",
     "project_id": "...",
     ...
   }'
   ```

5. **Share the sheet with the service account.** Copy its `client_email`
   (`something@your-project.iam.gserviceaccount.com`), then in your sheet click
   **Share**, paste it, and give it **Viewer**. Skip this and you'll get a 403,
   since the key by itself doesn't grant access to your sheet.
</details>

### 4. Pick your channels

Discord, email, or both. Each one sends independently, so a wrong Gmail
password won't cost you the Discord ping.

<details>
<summary><b>Discord</b> (the one that reliably reaches your phone)</summary>

A rich embed, colour-coded by urgency: red for overdue, amber for a new problem
due, blue for a rest day, green for a celebration.

1. Make a server, or use one you're in. Make a channel just for this.
2. Channel Settings → **Integrations → Webhooks → New Webhook → Copy Webhook
   URL**. That's `DISCORD_WEBHOOK_URL`.
3. Optional but recommended: User Settings → Advanced → **Developer Mode** on,
   then right-click yourself → **Copy User ID**. That's `DISCORD_USER_ID`.
   Nags @-mention you, which is what actually triggers a phone notification.
   Celebrations never mention anyone, so they arrive quietly.
</details>

<details>
<summary><b>Email</b> (Gmail or any SMTP server)</summary>

Sends a formatted HTML email, with a plain-text fallback.

1. Turn on **2-Step Verification** on the Google account you're sending from.
2. Create an app password at
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
   That 16-character string is `GMAIL_APP_PASSWORD`, **not** your normal
   password, which won't work.
3. Set `GMAIL_ADDRESS` (sent *from*) and `EMAIL_TO` (where it goes;
   comma-separate for several).

Not on Gmail? Set `SMTP_HOST` and `SMTP_PORT` to your provider's server. Both
587 (STARTTLS) and 465 (SSL) are handled. Put your username and password in
`GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` anyway.
</details>

### 5. Add the secrets and fire a test

**Settings → Secrets and variables → Actions → New repository secret**, one per
name. (Locally these go in `.env` instead. Copy `.env.example`, which is
gitignored. Same names in both places.)

| Secret | Needed for | What it is |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | always | The whole key file, pasted as one value |
| `SHEET_ID` | always | The long id in your sheet's URL, between `/d/` and `/edit` |
| `DISCORD_WEBHOOK_URL` | Discord | Channel Settings → Integrations → Webhooks |
| `DISCORD_USER_ID` | Discord | Your user id, so nags ping you |
| `GMAIL_ADDRESS` | email | The account nags are sent *from* |
| `GMAIL_APP_PASSWORD` | email | A Google App Password |
| `EMAIL_TO` | email | Where nags go |
| `SMTP_HOST`, `SMTP_PORT` | non-Gmail SMTP | Defaults to `smtp.gmail.com:587` |

Then: **Actions** tab → enable workflows → **leetcode-nag** → **Run workflow**.
That sends immediately regardless of the hour, so use it as your test button.

After that it fires once a day at your chosen hour. On days when nothing is
due, nothing is sent.

---

## Configuring it

`config.yml` is the file you edit. It covers behaviour only. Nothing in it is
secret or identifies you, so it's safe to commit in a public fork.

```yaml
list: blind75              # blind75 | neetcode150 | neetcode250

sheet:
  tab: Tracker             # tab name; blank = first tab

schedule:
  solve_days: [mon, tue, wed, thu, fri]   # or a preset: weekdays
  review_days: [sun]       # omit for every non-solve day; [] for never
  problems_per_day: 1
  timezone: America/New_York
  nag_hour: 19             # 0–23, local to `timezone`

review:
  enabled: true
  first_days: 7            # first review due 7 days after the cold attempt
  second_days: 21          # second review due 21 days after the cold attempt

stop_when_complete: true   # go quiet once the whole list is done

channels:
  discord: { enabled: true, mention: true }
  email:   { enabled: true, subject_prefix: "[LeetCode]" }
```

> ⚠️ **After changing `nag_hour` or `timezone`, run `python tools/sync_cron.py`
> and commit the result.** Actions cron is UTC-only and can't read
> `config.yml`, so the schedule lives in `.github/workflows/nag.yml` and that
> script is what keeps the two in sync. Don't hand-edit the cron lines.

<details>
<summary><b>Solve days, review days and streaks</b></summary>

Two independent sets of days, each written as a list or a preset. The presets
are `daily`, `weekdays`, `weekends`, `no_sundays`, and `none`.

- **`solve_days`** are the days the bot asks for a new cold attempt, and the
  days your streak is counted over. Rest days are skipped rather than breaking
  the streak.
- **`review_days`** are the days the bot tells you to re-read your notes.
  **Leave it out and it's every day you aren't solving**, which is what most
  people want.

A day can be both: on `solve_days: daily` you can still have `review_days:
[sun]` and get a notes nudge on Sunday alongside the usual ask. If a day is
both and you owe a new problem, the new problem wins.

Overdue spaced-repetition reviews are separate from all of this and get through
on **any** day, whatever these two are set to.

`problems_per_day` raises the bar: set it to `2` and a day only counts once two
cold attempts are logged with that date.
</details>

<details>
<summary><b>Review timing, and stopping</b></summary>

`first_days` counts from the cold attempt. `second_days` also counts from the
cold attempt, but the clock only starts once you've actually logged the first
review, so falling behind pushes the second one back instead of dumping both on
you at once. `review.enabled: false` turns review nagging off entirely.

With `stop_when_complete: true`, once every problem has a cold date and every
review is logged you get one final congratulations and then silence. Set it to
`false` to keep the review nagging going forever.
</details>

<details>
<summary><b>How it decides what to say</b></summary>

Every run:

1. Reads every row under the header.
2. Counts cold attempts dated today, and problems still without a cold date.
3. Finds overdue reviews: a `Cold ✓` with no first review older than
   `first_days`, or a first review with no second review older than
   `second_days - first_days`.
4. Computes the streak, meaning consecutive **solve days**, walking backwards,
   where you logged at least `problems_per_day`. Non-solve days are skipped
   rather than breaking it. Today doesn't count against you until you've done
   it.
5. Sends at most one nag per day, containing whichever apply:
   - **new problem due**, on a solve day where the quota isn't met and problems
     remain
   - **overdue reviews**, on any day
   - **review-day nudge**, to re-read your notes on what you've solved so far
   - if nothing applies, nothing is sent

Separately, and silently (no @-mention), it celebrates **25/50/75%** of the list
cold-attempted; **every problem cold-attempted** with reviews still outstanding
(a stretch everyone passes through, since the last problem's second review isn't
due until weeks after you solve it); and **finished**, meaning everything
attempted and every review logged.

Each fires once, and `state.json` remembers which have gone out. After the last
one, `stop_when_complete: true` retires the bot for good.
</details>

<details>
<summary><b>Notes on scheduled GitHub Actions</b></summary>

`nag.yml` carries one cron line per daylight-saving season, so it starts twice a
day. A gate step drops whichever run is in the wrong season in about five
seconds, before Python is even installed, which gets you two log entries a day
and one nag. Zones without DST get a single line and one entry.

- Runs can land 5–15 minutes late when GitHub is busy.
- **The schedule pauses after 60 days with no pushes to the repo.** The bot
  commits `state.json` back on days it sends something, which usually keeps the
  clock alive on its own.
- Public repos get unlimited Actions minutes. Private forks burn roughly 6
  minutes a day against the free 2,000/month.
- `python tools/sync_cron.py --check` exits non-zero if `config.yml` and the
  cron lines have drifted apart. CI runs it on every push.
</details>

---

## Troubleshooting

<details>
<summary><b>Nothing happens at all</b></summary>

Check the Actions tab. Forks have workflows disabled until you click through the
banner enabling them, and scheduled runs pause after 60 days of no pushes.
</details>

<details>
<summary><b>403 from Google</b></summary>

You didn't share the sheet with the service account's `client_email`, or the
Sheets API isn't enabled on the project. The error prints the exact address to
paste into the Share dialog.
</details>

<details>
<summary><b>"Couldn't read the tracker"</b></summary>

The message names the column it couldn't find. Either `sheet.tab` in
`config.yml` doesn't match your tab name (case- and space-sensitive), or the tab
is missing one of the four required columns: `Problem`, `Cold ✓ (date)`,
`1wk Review`, `3wk Review`.
</details>

<details>
<summary><b>"GOOGLE_SERVICE_ACCOUNT_JSON parsed, but it's missing…"</b></summary>

Only part of the key file made it into the variable. In `.env` the value must be
wrapped in single quotes so the multi-line JSON survives; without them only the
first line is read. Re-paste the whole file. This also fires if the placeholder
from `.env.example` is still in place.
</details>

<details>
<summary><b>It nagged and I'd already done the work</b></summary>

You logged the date in the wrong column, or in a format that didn't parse. Run
`python nag.py --dry-run --force` and check the counts on the first line.
</details>

<details>
<summary><b>Discord 403 · Gmail "Username and Password not accepted" · ModuleNotFoundError</b></summary>

- **Discord 403**: the webhook URL is wrong, or the webhook was deleted.
- **Gmail auth**: you used your account password instead of an App Password, or
  2-Step Verification isn't on.
- **`No module named 'dotenv'`**: you're running system Python instead of the
  virtualenv. Activate it, or call it directly:
  `venv/Scripts/python nag.py --dry-run`.
</details>

---

## Local development

```sh
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then fill it in

python nag.py --dry-run --force   # print what it would send, send nothing
python nag.py --test              # actually send, even if nothing is due
python nag.py --force             # normal run, ignoring the hour gate
python nag.py                     # exactly what the cron does
```

Use `--dry-run` to check that your sheet parses, and `--test` to check that your
channel credentials work. The exit code is 0 when everything sent (or there was
nothing to send), and 1 when an enabled and configured channel failed.

```sh
pip install -r requirements-dev.txt
python -m pytest tests/ -q        # offline: no network, no credentials
```

<details>
<summary><b>Repo layout, and regenerating the templates</b></summary>

```
nag.py                  entry point: gate, orchestration, exit codes
config.yml              your settings
nagger/
  config.py             loads and validates config.yml
  sheets.py             Google Sheets reads
  tracker.py            parses rows; works out what's due, overdue, streak
  messages.py           copy pools; builds the channel-agnostic report
  state.py              once-a-day and once-per-milestone dedup
  notify/               discord.py · mail.py
data/problems.json      the three problem lists, merged
templates/              blank tracker sheets, .xlsx and .csv
tools/                  regenerate the data and the templates
tests/                  offline tests
```

```sh
python tools/build_problem_data.py      # refresh data/problems.json upstream
python tools/make_template.py --all     # rebuild templates/
```
</details>

---

## Credits

Problem lists come from [NeetCode](https://neetcode.io). The `blind75` and
`neetcode150` membership flags come from
[neetcode-gh/leetcode](https://github.com/neetcode-gh/leetcode), and the
NeetCode 250 roadmap from
[ascherj/neetcode-250-guide](https://github.com/ascherj/neetcode-250-guide).

> The templates are generated from the public NeetCode lists, so a handful of
> problems are LeetCode Premium. The `NeetCode` column points at NeetCode, which
> has free versions of those.

MIT licensed. Fork it and change the insults if you like.
