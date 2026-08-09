"""Fan a report out to every enabled channel.

One failing channel never stops the others — an expired Gmail app password
shouldn't cost you the Discord ping. `dispatch` returns the per-channel
outcome and the caller decides what a failure means for the exit code.
"""

from __future__ import annotations

import sys

from ..config import Channels
from ..messages import Report
from . import discord, mail


def dispatch(report: Report, channels: Channels, *, dry_run: bool = False) -> dict[str, str]:
    """Returns {channel: "sent" | "skipped: …" | "failed: …"}."""
    results: dict[str, str] = {}

    senders = []
    if channels.discord.enabled:
        senders.append((
            "discord",
            discord.configured,
            lambda: discord.send(report, channels.discord.mention),
            "DISCORD_WEBHOOK_URL is not set",
        ))
    if channels.email.enabled:
        senders.append((
            "email",
            mail.configured_for_email,
            lambda: mail.send(report, channels.email.subject_prefix),
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD / EMAIL_TO are not all set",
        ))

    for name, is_configured, send, missing in senders:
        if not is_configured():
            results[name] = f"skipped: {missing}"
            print(f"  {name}: skipped — {missing}", file=sys.stderr)
            continue
        if dry_run:
            results[name] = "skipped: dry run"
            print(f"  {name}: would send")
            continue
        try:
            send()
            results[name] = "sent"
            print(f"  {name}: sent")
        # SystemExit is caught deliberately: a missing env var deep in a sender
        # calls sys.exit, and SystemExit isn't an Exception — uncaught, it would
        # abort the run and skip every channel after this one.
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            results[name] = f"failed: {exc}"
            print(f"  {name}: FAILED — {exc}", file=sys.stderr)

    return results


def any_sent(results: dict[str, str]) -> bool:
    return any(v == "sent" for v in results.values())


def any_failed(results: dict[str, str]) -> bool:
    return any(v.startswith("failed") for v in results.values())
