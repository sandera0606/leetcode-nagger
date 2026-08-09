"""LeetCode nag bot — entry point.

Reads your tracker tab out of Google Sheets, works out what's due today, and
pushes a nag to whichever channels you've enabled in config.yml.

    python nag.py                # respects the configured nag hour
    python nag.py --ignore-hour  # send whenever it runs, but once a day at most
    python nag.py --force        # ignore the hour gate and the once-a-day lock
    python nag.py --dry-run      # print what would be sent, send nothing
    python nag.py --test         # send a real message even if nothing is due
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from nagger import notify, sheets
from nagger.config import env, load_config
from nagger.messages import (
    MILESTONES,
    build_all_cold_report,
    build_complete_report,
    build_milestone_report,
    build_report,
)
from nagger.state import State
from nagger.tracker import build_status, find_header, parse_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="ignore the nag-hour gate and the one-per-day lock")
    parser.add_argument("--ignore-hour", action="store_true",
                        help="ignore the nag-hour gate but keep the one-per-day lock")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the message instead of sending it")
    parser.add_argument("--test", action="store_true",
                        help="send even when nothing is due (implies --force)")
    parser.add_argument("--config", type=Path, default=None,
                        help="path to config.yml (default: repo root)")
    return parser.parse_args()


def preview(report) -> None:
    print(f"\n--- {report.kind}: {report.title} ---")
    for section in report.sections:
        print(f"\n{section.title}")
        for line in section.lines:
            print(f"  {line}")
    print(f"\n{report.footer}")
    print(f"URL: {report.url}\n")


def main() -> int:
    args = parse_args()
    force = args.force or args.test
    load_dotenv()
    cfg = load_config(args.config)

    now = datetime.now(ZoneInfo(cfg.schedule.timezone))
    today = now.date()
    if not force and not args.ignore_hour and now.hour != cfg.schedule.nag_hour:
        print(f"{now:%H:%M %Z} — nag hour is {cfg.schedule.nag_hour:02d}:00. Nothing to do.")
        return 0

    sheet_id = env("SHEET_ID", required=True,
                   hint="the long id in your sheet's URL, between /d/ and /edit")
    client = sheets.build_client()
    gid = sheets.fetch_gid(client, sheet_id, cfg.sheet_tab)
    url = sheets.sheet_url(sheet_id, gid)

    rows = sheets.fetch_rows(client, sheet_id, cfg.sheet_tab)
    header_idx, cols = find_header(rows)
    problems = parse_rows(rows[header_idx + 1:], cols)
    if not problems:
        sys.exit("Found the header row but no problem rows under it. Is the tab empty?")

    status = build_status(problems, today, cfg)
    print(
        f"{today.isoformat()} · {status.solved}/{status.total} solved · "
        f"{status.done_today} today · {len(status.overdue_first)}+"
        f"{len(status.overdue_second)} overdue · {status.streak}d streak"
    )

    state = State()
    exit_code = 0

    # ---- celebrations (silent, deduped, independent of the nag) ---------
    # Most specific first. `all_cold_done` has to sit between the other two:
    # at 100% solved every milestone threshold matches, so without it the bot
    # congratulates you on 75% while the body reads 75/75 — and that window
    # lasts until the final review falls due, weeks later.
    celebration = None
    if status.complete:
        celebration = (f"{cfg.list_key}:complete",
                       lambda: build_complete_report(status, url, cfg.list_name))
    elif status.all_cold_done:
        celebration = (f"{cfg.list_key}:all-cold",
                       lambda: build_all_cold_report(status, url, cfg.list_name))
    else:
        reached = [m for m in MILESTONES if status.percent >= m]
        if reached:
            milestone = max(reached)
            celebration = (f"{cfg.list_key}:{milestone}",
                           lambda: build_milestone_report(status, url, cfg.list_name, milestone))

    if celebration:
        key, build = celebration
        if not state.has_celebrated(key):
            report = build()
            if args.dry_run:
                preview(report)
            results = notify.dispatch(report, cfg.channels, dry_run=args.dry_run)
            if notify.any_sent(results):
                state.mark_celebrated(key)
                state.save()

    if status.complete and cfg.stop_when_complete:
        print(f"{cfg.list_name} is finished. Nothing left to nag about.")
        return exit_code

    # ---- the nag ---------------------------------------------------------
    review_nudge = status.is_review_day
    if not (status.needs_new or status.has_overdue or review_nudge or args.test):
        print("All clear. Nothing to nag about.")
        return exit_code

    if state.nagged_today(today) and not force:
        print("Already nagged today. Staying quiet.")
        return exit_code

    report = build_report(status, url, cfg.list_name, cfg.channels.discord.mention)
    if args.dry_run:
        preview(report)
    results = notify.dispatch(report, cfg.channels, dry_run=args.dry_run)
    if notify.any_sent(results):
        state.mark_nagged(today)
        state.save()
    if notify.any_failed(results):
        exit_code = 1
    if not results:
        print("No channels enabled — check `channels:` in config.yml.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
