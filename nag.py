"""LeetCode nag bot.

Reads a Google Sheet via Composio, finds today's scheduled problem, and if
date_completed doesn't contain today's date, sends a nag through Gmail
(required) plus Twilio SMS and Discord (both optional — skipped if their env
vars are blank).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime

from composio import Action, ComposioToolSet
from dotenv import load_dotenv

load_dotenv()

REQUIRED_HEADERS = ("scheduled_date", "problem", "difficulty", "date_completed")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing required env var: {name}")
    return value


def env_opt(name: str) -> str:
    return os.environ.get(name, "").strip()


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


def cell_contains(cell: str, today: date) -> bool:
    parsed = parse_date(cell)
    if parsed is not None:
        return parsed == today
    return today.isoformat() in cell


def fetch_rows(toolset: ComposioToolSet, sheet_id: str, tab: str) -> list[list[str]]:
    # If tab is blank, the API returns the first sheet. Tab names with spaces
    # or special chars need single quotes around them in the range string.
    range_ = f"'{tab}'!A:Z" if tab else "A:Z"
    result = toolset.execute_action(
        action=Action.GOOGLESHEETS_BATCH_GET,
        params={"spreadsheet_id": sheet_id, "ranges": [range_]},
    )
    if not result.get("successful", result.get("successfull", False)):
        sys.exit(f"Google Sheets read failed: {result.get('error') or result}")
    data = result.get("data", {})
    value_ranges = data.get("valueRanges") or data.get("value_ranges") or []
    if not value_ranges:
        return []
    return value_ranges[0].get("values", []) or []


def find_today(rows: list[list[str]], today: date) -> dict[str, str] | None:
    if not rows:
        return None
    header = [h.strip().lower() for h in rows[0]]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        sys.exit(f"Sheet header missing required columns: {missing}")
    idx = {h: header.index(h) for h in REQUIRED_HEADERS}

    for row in rows[1:]:
        padded = row + [""] * (len(header) - len(row))
        if cell_contains(padded[idx["scheduled_date"]], today):
            return {h: padded[idx[h]] for h in REQUIRED_HEADERS}
    return None


def send_email(toolset: ComposioToolSet, recipient: str, subject: str, body: str) -> None:
    toolset.execute_action(
        action=Action.GMAIL_SEND_EMAIL,
        params={
            "recipient_email": recipient,
            "subject": subject,
            "body": body,
            "is_html": False,
        },
    )


def send_sms(toolset: ComposioToolSet, to_number: str, from_number: str, body: str) -> None:
    toolset.execute_action(
        action=Action.TWILIO_SEND_AN_SMS_MESSAGE,
        params={"to": to_number, "from_": from_number, "body": body},
    )


def send_discord(webhook_url: str, content: str) -> None:
    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook returned {resp.status}")


def main() -> int:
    api_key = env("COMPOSIO_API_KEY")
    sheet_id = env("SHEET_ID")
    sheet_tab = env_opt("SHEET_TAB")
    entity_id = env("COMPOSIO_ENTITY_ID")
    recipient_email = env("RECIPIENT_EMAIL")
    twilio_to = env_opt("TWILIO_TO_NUMBER")
    twilio_from = env_opt("TWILIO_FROM_NUMBER")
    discord_webhook = env_opt("DISCORD_WEBHOOK_URL")

    today = date.today()
    toolset = ComposioToolSet(api_key=api_key, entity_id=entity_id)

    rows = fetch_rows(toolset, sheet_id, sheet_tab)
    row = find_today(rows, today)

    if row is None:
        print(f"No problem scheduled for {today.isoformat()} — nothing to nag about.")
        return 0

    if cell_contains(row["date_completed"], today):
        print(f"Already done: {row['problem']} ({row['difficulty']}). No nag.")
        return 0

    problem = row["problem"]
    difficulty = row["difficulty"]
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    subject = f"LeetCode nag: {problem} ({difficulty}) is still undone"
    body = (
        f"You haven't completed today's LeetCode problem.\n\n"
        f"  Problem:    {problem}\n"
        f"  Difficulty: {difficulty}\n"
        f"  Scheduled:  {today.isoformat()}\n\n"
        f"Tracker: {sheet_url}\n\n"
        f"Stop procrastinating and go solve it."
    )
    sms = (
        f"LeetCode nag: {problem} ({difficulty}) is still undone for "
        f"{today.isoformat()}. Tracker: {sheet_url}"
    )

    channels: list[tuple[str, object]] = [
        ("email", lambda: send_email(toolset, recipient_email, subject, body)),
    ]
    if twilio_to and twilio_from:
        channels.append(("sms", lambda: send_sms(toolset, twilio_to, twilio_from, sms)))
    else:
        print("  skipped sms (TWILIO_TO_NUMBER / TWILIO_FROM_NUMBER not set)")
    if discord_webhook:
        channels.append(("discord", lambda: send_discord(discord_webhook, sms)))
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
