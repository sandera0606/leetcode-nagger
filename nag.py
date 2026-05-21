"""LeetCode nag bot.

Reads a Blind 75 tracker + a Master Schedule from Google Sheets via Composio.
Computes what's due today (overdue 1wk/3wk reviews, plus new cold attempts if
the week's quota isn't yet met) and sends a nag through Gmail (required) and
an optional Discord webhook. On Sundays, swaps the new-problem nag for a
"re-read your notes" reminder.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import random
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from composio import Composio
from dotenv import load_dotenv

load_dotenv()

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
)
MAX_LISTED_PROBLEMS = 30  # Discord has a 2000-char body cap; trim long lists.


# ---- env helpers --------------------------------------------------------

def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing required env var: {name}")
    return value


def env_opt(name: str) -> str:
    return os.environ.get(name, "").strip()


# ---- parsing helpers ----------------------------------------------------

def parse_date(cell: str) -> date | None:
    cell = cell.strip()
    if not cell:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cell, fmt).date()
        except ValueError:
            continue
    return None


def parse_month(name: str) -> int | None:
    norm = name.strip().lower().capitalize()
    for fmt in ("%b", "%B"):
        try:
            return datetime.strptime(norm, fmt).month
        except ValueError:
            continue
    return None


def parse_date_range(s: str, year: int) -> tuple[date, date] | None:
    """Parse strings like 'May 20-24' or 'June 29-Jul 3' into (start, end)."""
    s = s.strip()
    cross = re.match(r"^([A-Za-z]+)\s+(\d+)\s*[-–]\s*([A-Za-z]+)\s+(\d+)$", s)
    if cross:
        m1 = parse_month(cross.group(1))
        m2 = parse_month(cross.group(3))
        if m1 and m2:
            return date(year, m1, int(cross.group(2))), date(year, m2, int(cross.group(4)))
    same = re.match(r"^([A-Za-z]+)\s+(\d+)\s*[-–]\s*(\d+)$", s)
    if same:
        m = parse_month(same.group(1))
        if m:
            return date(year, m, int(same.group(2))), date(year, m, int(same.group(3)))
    return None


def norm(s: str) -> str:
    return s.strip().lower()


# ---- Composio fetch -----------------------------------------------------

def fetch_sheet_gid(client: Composio, user_id: str, sheet_id: str, tab: str) -> str | None:
    """Look up the numeric sheetId (gid) for a tab so the URL can deep-link to it."""
    if not tab:
        return None
    result = client.tools.execute(
        slug="GOOGLESHEETS_GET_SPREADSHEET_INFO",
        arguments={
            "spreadsheet_id": sheet_id,
            "fields": "sheets.properties(sheetId,title)",
        },
        user_id=user_id,
    )
    if not result.get("successful", False):
        return None
    data = result.get("data", {}) or {}
    for sheet in data.get("sheets", []) or []:
        props = sheet.get("properties", {}) or {}
        if props.get("title") == tab:
            sid = props.get("sheetId")
            return str(sid) if sid is not None else None
    return None


def fetch_rows(client: Composio, user_id: str, sheet_id: str, tab: str) -> list[list[str]]:
    range_ = f"'{tab}'!A:Z" if tab else "A:Z"
    result = client.tools.execute(
        slug="GOOGLESHEETS_BATCH_GET",
        arguments={"spreadsheet_id": sheet_id, "ranges": [range_]},
        user_id=user_id,
    )
    if not result.get("successful", False):
        sys.exit(f"Google Sheets read failed for tab '{tab}': {result.get('error') or result}")
    data = result.get("data", {}) or {}
    value_ranges = data.get("valueRanges") or data.get("value_ranges") or []
    if not value_ranges:
        return []
    return value_ranges[0].get("values", []) or []


# ---- tracker tab --------------------------------------------------------

@dataclass
class ProblemRow:
    problem: str
    difficulty: str
    cold: date | None
    one_wk: date | None
    three_wk: date | None


def find_tracker_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows):
        cols: dict[str, int] = {}
        for j, c in enumerate(row):
            nc = norm(c)
            if nc == "problem":
                cols["problem"] = j
            elif nc in ("diff", "difficulty"):
                cols["difficulty"] = j
            elif "cold" in nc and "date" in nc:
                cols["cold"] = j
            elif "1wk" in nc or "1 wk" in nc or "1 week" in nc:
                cols["1wk"] = j
            elif "3wk" in nc or "3 wk" in nc or "3 week" in nc:
                cols["3wk"] = j
        if {"problem", "difficulty", "cold", "1wk", "3wk"}.issubset(cols):
            return i, cols
    sys.exit(
        "Couldn't find tracker header. Need columns: Problem, Diff/Difficulty, "
        "Cold ✓ (date), 1wk Review, 3wk Review (any case)."
    )


def parse_tracker(rows: list[list[str]], cols: dict[str, int]) -> list[ProblemRow]:
    max_col = max(cols.values())
    out: list[ProblemRow] = []
    for row in rows:
        if not row or not any(c.strip() for c in row):
            continue
        padded = row + [""] * (max_col + 1 - len(row))
        problem = padded[cols["problem"]].strip()
        if not problem:
            continue
        out.append(ProblemRow(
            problem=problem,
            difficulty=padded[cols["difficulty"]].strip(),
            cold=parse_date(padded[cols["cold"]]),
            one_wk=parse_date(padded[cols["1wk"]]),
            three_wk=parse_date(padded[cols["3wk"]]),
        ))
    return out


# ---- schedule tab -------------------------------------------------------

@dataclass
class WeekRow:
    start: date
    end: date
    target: int


def find_schedule_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows):
        cols: dict[str, int] = {}
        for j, c in enumerate(row):
            nc = norm(c)
            if nc == "dates":
                cols["dates"] = j
            elif nc in ("# new", "#new", "new", "lc target", "leetcode target", "target"):
                cols["target"] = j
        if {"dates", "target"}.issubset(cols):
            return i, cols
    return None


def parse_schedule(rows: list[list[str]], cols: dict[str, int], year: int) -> list[WeekRow]:
    max_col = max(cols.values())
    out: list[WeekRow] = []
    for row in rows:
        if not row or not any(c.strip() for c in row):
            continue
        padded = row + [""] * (max_col + 1 - len(row))
        rng = parse_date_range(padded[cols["dates"]], year)
        if rng is None:
            continue
        try:
            target = int(padded[cols["target"]].strip())
        except ValueError:
            continue
        out.append(WeekRow(start=rng[0], end=rng[1], target=target))
    out.sort(key=lambda w: w.start)
    return out


def current_week(weeks: list[WeekRow], today: date) -> WeekRow | None:
    """Latest week whose start date is on or before today. Extends through gap
    days into the next week's start, so weekends/off-days still resolve."""
    match = None
    for w in weeks:
        if w.start <= today:
            match = w
        else:
            break
    return match


def weekly_streak(weeks: list[WeekRow], problems: list[ProblemRow], today: date) -> int | None:
    """Consecutive *completed* weeks (week.end < today) ending at the most
    recent one where cold attempts in [start, end] met the # New target.
    Returns None when no week has fully completed yet."""
    completed = sorted((w for w in weeks if w.end < today), key=lambda w: w.start, reverse=True)
    if not completed:
        return None
    streak = 0
    for w in completed:
        count = sum(1 for p in problems if p.cold and w.start <= p.cold <= w.end)
        if count >= w.target:
            streak += 1
        else:
            break
    return streak


# ---- senders ------------------------------------------------------------

def send_email(client: Composio, user_id: str, recipient: str, subject: str, body: str, *, is_html: bool = False) -> None:
    result = client.tools.execute(
        slug="GMAIL_SEND_EMAIL",
        arguments={
            "recipient_email": recipient,
            "subject": subject,
            "body": body,
            "is_html": is_html,
        },
        user_id=user_id,
    )
    if not result.get("successful", False):
        raise RuntimeError(result.get("error") or result)


def send_discord(webhook_url: str, embed: dict, mention_user_id: str = "") -> None:
    # Discord Cloudflare-blocks Python's default "Python-urllib/X.Y" UA with
    # 403, so set an explicit one.
    body: dict[str, object] = {"embeds": [embed]}
    if mention_user_id:
        # allowed_mentions whitelists this user explicitly — guards against
        # accidental @everyone if content ever contained one.
        body["content"] = f"<@{mention_user_id}>"
        body["allowed_mentions"] = {"users": [mention_user_id]}
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "leetcode-nagger (https://github.com/, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook returned {resp.status}")


# ---- HTML email rendering ----------------------------------------------

CARD_STYLES = {
    "sunday":       {"bg": "#dbeafe", "border": "#2563eb", "text": "#1e3a8a"},
    "new":          {"bg": "#fef3c7", "border": "#d97706", "text": "#78350f"},
    "overdue":      {"bg": "#fee2e2", "border": "#dc2626", "text": "#7f1d1d"},
    "streak_alive": {"bg": "#d1fae5", "border": "#059669", "text": "#064e3b"},
    "streak_zero":  {"bg": "#e5e7eb", "border": "#6b7280", "text": "#374151"},
}


# ---- message pools ------------------------------------------------------

SUBJECT_POOLS = [
    "LeetCode nag ({date}): {summary}",
    "Hey. {summary}. ({date})",
    "Your tracker is unimpressed ({date}): {summary}",
    "I'm not mad, just disappointed ({date}): {summary}",
    "We need to talk ({date}): {summary}",
    "Procrastinating again? {summary}. ({date})",
    "{summary}. The interviewers are watching. ({date})",
    "Reminder from future unemployed-you ({date}): {summary}",
    "The Blind 75 has a long memory ({date}): {summary}",
    "{summary}. Get to work. ({date})",
    "Knock knock ({date}). It's {summary}.",
    "I see you avoiding LeetCode ({date}): {summary}",
    "Your future FAANG offer is crying ({date}): {summary}",
    "Tick tock ({date}): {summary}",
    "Hi. It's me. Your tracker. ({date}): {summary}",
    "You know what to do ({date}): {summary}",
    "Don't make me come over there ({date}): {summary}",
]

NEW_COLD_TITLES = [
    "Do a new cold attempt today.",
    "Pick a problem. Solve it. That's it.",
    "Today's tribute: one cold attempt.",
    "A wild LeetCode problem appears.",
    "Future-you is begging for one cold attempt.",
    "One problem. That's the whole ask.",
    "New cold attempt. Now. Yes, now.",
    "The schedule says: one new problem today.",
    "Crack open LeetCode. Pick anything. Go.",
]

SUNDAY_WITH_NOTES_TITLES = [
    "It's Sunday. No new problems today.",
    "Sunday. Time to re-read what you 'learned'.",
    "Review day. Yes, even when you don't feel like it.",
    "Sunday means notes. Don't make excuses.",
    "It's notes-review day. Don't skim.",
]

SUNDAY_WITH_NOTES_SUBTITLES = [
    "Re-read your notes on the {n} problem(s) you've cold-attempted.",
    "Open your notes for these {n} problem(s). All of them.",
    "{n} problem(s) need a refresher. Don't skim.",
    "Time to revisit {n} problem(s). Be thorough.",
]

SUNDAY_EMPTY_TITLES = [
    "It's Sunday.",
    "Sunday and your tracker is bare.",
    "A suspiciously quiet Sunday.",
]

SUNDAY_EMPTY_SUBTITLES = [
    "No cold attempts on record yet — start fresh Monday.",
    "Nothing logged yet. Monday is your fresh start.",
    "Empty tracker. Fix it Monday.",
]

OVERDUE_1WK_TITLES = [
    "{n} 1-week review(s) overdue",
    "{n} problem(s) waiting to be re-solved — they're getting cold",
    "{n} 1-week review(s) you've been avoiding",
    "{n} 1-week review(s). Tick tock.",
    "{n} 1-week review(s) aging in your tracker",
]

OVERDUE_3WK_TITLES = [
    "{n} 3-week review(s) overdue",
    "{n} 3-week review(s) — the solutions are fading from your brain",
    "{n} 3-week review(s). You barely remember solving these.",
    "{n} 3-week review(s). Spaced repetition wants a word.",
    "{n} 3-week review(s). Past-you would be disappointed.",
]

STREAK_TITLES_ALIVE = [
    "Streak: {n} week(s). Don't be the reason it ends.",
    "Streak: {n} week(s). Keep it alive.",
    "{n}-week streak. Don't blow it now.",
    "Streak holding: {n} week(s). One miss and it's gone.",
    "{n} weeks on streak. Future-you is proud. Don't ruin it.",
]

STREAK_TITLES_ZERO = [
    "Streak: 0. From the ashes, etc.",
    "No streak right now. Time to start one.",
    "0-week streak. Last week's quota wasn't met.",
    "Streak: 0. Embarrassing. Fix it.",
]

FOOTER_LINES = [
    "Stop procrastinating.",
    "The job market won't wait.",
    "Future-you is watching.",
    "One problem at a time.",
    "Past-you scheduled this for a reason.",
    "Get back to it.",
    "No excuses.",
    "Don't ghost your own tracker.",
    "The algorithm gods demand tribute.",
    "Solve a problem. Don't think. Solve.",
]


def pick(pool: list[str], **kw: object) -> str:
    return random.choice(pool).format(**kw)


def esc(s: str) -> str:
    return html_lib.escape(s, quote=False)


def html_card(kind: str, title: str, subtitle: str | None = None,
              items_html: list[str] | None = None, more: int = 0) -> str:
    s = CARD_STYLES.get(kind, CARD_STYLES["new"])
    parts = [
        f'<div style="background:{s["bg"]};border-left:4px solid {s["border"]};'
        f'padding:14px 18px;margin:0 0 12px;border-radius:4px;color:{s["text"]};">',
        f'<div style="font-weight:600;font-size:15px;line-height:1.35;">{title}</div>',
    ]
    if subtitle:
        parts.append(
            f'<div style="font-size:13px;opacity:0.85;margin-top:4px;">{subtitle}</div>'
        )
    if items_html:
        parts.append('<ul style="margin:10px 0 0;padding-left:20px;font-size:14px;">')
        for it in items_html:
            parts.append(f'<li style="margin:3px 0;">{it}</li>')
        if more > 0:
            parts.append(
                f'<li style="margin:3px 0;list-style:none;opacity:0.7;">'
                f'…and {more} more</li>'
            )
        parts.append('</ul>')
    parts.append('</div>')
    return ''.join(parts)


def build_html_body(today: date, cards: list[str], sheet_url: str, footer: str) -> str:
    pretty_date = f"{today.strftime('%A')}, {today.strftime('%B')} {today.day}, {today.year}"
    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:24px 12px;'
        "background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2937;\">"
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;'
        'border-radius:8px;padding:28px 24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        '<div style="border-bottom:1px solid #e5e7eb;padding-bottom:14px;margin-bottom:18px;">'
        '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#dc2626;">LeetCode Nag</div>'
        f'<div style="margin-top:4px;color:#6b7280;font-size:14px;">{esc(pretty_date)}</div>'
        '</div>'
        + ''.join(cards) +
        f'<div style="margin-top:20px;"><a href="{esc(sheet_url)}" '
        'style="display:inline-block;background:#111827;color:#ffffff;'
        'padding:10px 20px;text-decoration:none;border-radius:6px;'
        'font-weight:500;font-size:14px;">Open Tracker →</a></div>'
        '<div style="margin-top:28px;color:#9ca3af;font-size:13px;font-style:italic;">'
        f'{esc(footer)}</div>'
        '</div></body></html>'
    )


# ---- Discord embed rendering -------------------------------------------

DISCORD_COLORS = {
    "overdue": 0xDC2626,  # red — overdue beats everything
    "new":     0xD97706,  # amber — cold attempt pending
    "sunday":  0x2563EB,  # blue — review day
}


def build_discord_embed(today: date, sheet_url: str, sections: list[dict], footer: str) -> dict:
    # Streak sections don't drive the embed color — actionable kinds do.
    kinds = {s["kind"] for s in sections}
    color = (
        DISCORD_COLORS["overdue"] if "overdue" in kinds
        else DISCORD_COLORS["new"] if "new" in kinds
        else DISCORD_COLORS["sunday"]
    )
    pretty_date = f"{today.strftime('%A')}, {today.strftime('%B')} {today.day}"
    return {
        "title": f"LeetCode Nag · {pretty_date}",
        "url": sheet_url,
        "color": color,
        # Discord field value cap is 1024 chars per field; trim defensively.
        "fields": [
            {"name": s["name"][:256], "value": s["value"][:1024], "inline": False}
            for s in sections
        ],
        "footer": {"text": footer},
    }


# ---- main ---------------------------------------------------------------

def main() -> int:
    api_key = env("COMPOSIO_API_KEY")
    sheet_id = env("SHEET_ID")
    entity_id = env("COMPOSIO_ENTITY_ID")
    recipient_email = env("RECIPIENT_EMAIL")
    sheet_tab = env_opt("SHEET_TAB")
    schedule_tab = env_opt("SCHEDULE_TAB")
    discord_webhook = env_opt("DISCORD_WEBHOOK_URL")
    discord_user_id = env_opt("DISCORD_USER_ID")

    today = date.today()
    is_sunday = today.weekday() == 6
    client = Composio(
        api_key=api_key,
        toolkit_versions={
            "googlesheets": "20260512_00",
            "gmail": "20260515_00",
        },
    )

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    gid = fetch_sheet_gid(client, entity_id, sheet_id, sheet_tab)
    if gid is not None:
        sheet_url += f"#gid={gid}"

    # Tracker tab — required
    tracker_raw = fetch_rows(client, entity_id, sheet_id, sheet_tab)
    h_idx, h_cols = find_tracker_header(tracker_raw)
    problems = parse_tracker(tracker_raw[h_idx + 1:], h_cols)

    # Master Schedule — optional
    weeks: list[WeekRow] = []
    week: WeekRow | None = None
    if schedule_tab:
        sched_raw = fetch_rows(client, entity_id, sheet_id, schedule_tab)
        sched_header = find_schedule_header(sched_raw)
        if sched_header:
            s_idx, s_cols = sched_header
            weeks = parse_schedule(sched_raw[s_idx + 1:], s_cols, today.year)
            week = current_week(weeks, today)
        else:
            print(f"Warning: '{schedule_tab}' has no recognisable Dates + LC Target columns.", file=sys.stderr)

    # Compute state
    overdue_1wk: list[tuple[str, str, int]] = []
    overdue_3wk: list[tuple[str, str, int]] = []
    completed_problems: list[str] = []
    cold_this_week = 0
    cold_today_count = 0

    for p in problems:
        if p.cold:
            completed_problems.append(p.problem)
            if p.cold == today:
                cold_today_count += 1
            if week and week.start <= p.cold <= today:
                cold_this_week += 1
        if p.cold and not p.one_wk:
            due = p.cold + timedelta(days=7)
            if today >= due:
                overdue_1wk.append((p.problem, p.difficulty, (today - due).days))
        if p.one_wk and not p.three_wk:
            due = p.one_wk + timedelta(days=14)
            if today >= due:
                overdue_3wk.append((p.problem, p.difficulty, (today - due).days))

    week_quota_met = week is not None and cold_this_week >= week.target
    needs_new_cold = (not is_sunday) and (not week_quota_met) and (cold_today_count == 0)

    # Decide whether to send anything
    if not is_sunday and not needs_new_cold and not overdue_1wk and not overdue_3wk:
        print(f"All clear for {today.isoformat()}. Nothing to nag.")
        return 0

    # Build text + HTML + Discord-embed sections in parallel
    text_sections: list[str] = []
    html_cards: list[str] = []
    discord_sections: list[dict] = []
    summary: list[str] = []

    if is_sunday:
        if completed_problems:
            shown = completed_problems[:MAX_LISTED_PROBLEMS]
            extra = len(completed_problems) - len(shown)
            title = pick(SUNDAY_WITH_NOTES_TITLES)
            subtitle = pick(SUNDAY_WITH_NOTES_SUBTITLES, n=len(completed_problems))
            text_lines = [title, f"{subtitle}:"]
            for name in shown:
                text_lines.append(f"    - {name}")
            if extra > 0:
                text_lines.append(f"    ...and {extra} more")
            text_sections.append("\n".join(text_lines))
            html_cards.append(html_card(
                kind="sunday",
                title=title,
                subtitle=subtitle,
                items_html=[esc(p) for p in shown],
                more=extra,
            ))
            discord_value = f"{subtitle}\n" + "\n".join(f"• {n}" for n in shown)
            if extra > 0:
                discord_value += f"\n_…and {extra} more_"
            discord_sections.append({
                "kind": "sunday",
                "name": title,
                "value": discord_value,
            })
        else:
            title = pick(SUNDAY_EMPTY_TITLES)
            subtitle = pick(SUNDAY_EMPTY_SUBTITLES)
            text_sections.append(f"{title} {subtitle}")
            html_cards.append(html_card(
                kind="sunday", title=title, subtitle=subtitle,
            ))
            discord_sections.append({
                "kind": "sunday",
                "name": title,
                "value": subtitle,
            })
        summary.append("Sunday note review")
    elif needs_new_cold:
        title = pick(NEW_COLD_TITLES)
        if week:
            subtitle = f"{cold_this_week}/{week.target} done this week."
            text_sections.append(f"{title} {subtitle}")
            html_cards.append(html_card(kind="new", title=title, subtitle=subtitle))
            discord_sections.append({
                "kind": "new",
                "name": title,
                "value": f"**{cold_this_week}/{week.target}** done this week.",
            })
        else:
            text_sections.append(title)
            html_cards.append(html_card(kind="new", title=title))
            discord_sections.append({
                "kind": "new",
                "name": title,
                "value": "New cold attempt pending.",
            })
        summary.append("new cold attempt pending")

    for label, items, pool in (
        ("1-week", overdue_1wk, OVERDUE_1WK_TITLES),
        ("3-week", overdue_3wk, OVERDUE_3WK_TITLES),
    ):
        if not items:
            continue
        shown = items[:MAX_LISTED_PROBLEMS]
        extra = len(items) - len(shown)
        title = pick(pool, n=len(items))
        text_lines = [f"{title}:"]
        for name, diff, days in shown:
            text_lines.append(f"    - {name} ({diff}) - {days}d overdue")
        if extra > 0:
            text_lines.append(f"    ...and {extra} more")
        text_sections.append("\n".join(text_lines))
        html_cards.append(html_card(
            kind="overdue",
            title=title,
            items_html=[
                f"{esc(name)} <span style=\"opacity:0.7;\">({esc(diff)})</span> "
                f"— <strong>{days}d overdue</strong>"
                for name, diff, days in shown
            ],
            more=extra,
        ))
        discord_lines = [
            f"• **{name}** _({diff})_ — **{days}d overdue**"
            for name, diff, days in shown
        ]
        if extra > 0:
            discord_lines.append(f"_…and {extra} more_")
        discord_sections.append({
            "kind": "overdue",
            "name": title,
            "value": "\n".join(discord_lines),
        })
        summary.append(f"{len(items)} {label.replace('-week','wk')} overdue")

    # Streak card — prepended so it shows first. Only when we have at least
    # one fully-completed scheduled week to derive a streak from.
    streak = weekly_streak(weeks, problems, today) if weeks else None
    if streak is not None:
        if streak >= 1:
            streak_title = pick(STREAK_TITLES_ALIVE, n=streak)
            streak_kind = "streak_alive"
            streak_value = f"**{streak}**-week streak."
        else:
            streak_title = pick(STREAK_TITLES_ZERO)
            streak_kind = "streak_zero"
            streak_value = "Streak: **0**."
        text_sections.insert(0, streak_title)
        html_cards.insert(0, html_card(kind=streak_kind, title=streak_title))
        discord_sections.insert(0, {
            "kind": streak_kind,
            "name": streak_title,
            "value": streak_value,
        })

    summary_text = "; ".join(summary) if summary else "check in"
    date_str = f"{today.strftime('%a')} {today.isoformat()}"
    subject = pick(SUBJECT_POOLS, date=date_str, summary=summary_text)
    footer = pick(FOOTER_LINES)
    text_body = (
        f"{subject}\n\n"
        + "\n\n".join(text_sections)
        + f"\n\nTracker: {sheet_url}\n\n{footer}"
    )
    html_body = build_html_body(today, html_cards, sheet_url, footer)
    discord_embed = build_discord_embed(today, sheet_url, discord_sections, footer)

    channels: list[tuple[str, object]] = [
        ("email", lambda: send_email(client, entity_id, recipient_email, subject, html_body, is_html=True)),
    ]
    if discord_webhook:
        channels.append(("discord", lambda: send_discord(discord_webhook, discord_embed, discord_user_id)))
    else:
        print("  skipped discord (DISCORD_WEBHOOK_URL not set)")

    failures: list[str] = []
    for label, fn in channels:
        try:
            fn()
            print(f"  sent {label}")
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            print(f"  FAILED {label}: {exc}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} channel(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
