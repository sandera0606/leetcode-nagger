"""Discord webhook delivery."""

from __future__ import annotations

import json
import urllib.request

from ..config import env
from ..messages import Report


def configured() -> bool:
    return bool(env("DISCORD_WEBHOOK_URL"))


def send(report: Report, mention: bool) -> None:
    webhook = env(
        "DISCORD_WEBHOOK_URL",
        required=True,
        hint="Channel Settings → Integrations → Webhooks → Copy Webhook URL",
    )
    embed = {
        "title": report.title[:256],
        "url": report.url,
        "color": report.color,
        # Discord caps a field value at 1024 chars.
        "fields": [
            {"name": s.title[:256], "value": s.body[:1024], "inline": False}
            for s in report.sections
        ],
        "footer": {"text": report.footer},
    }
    body: dict[str, object] = {"embeds": [embed]}

    user_id = env("DISCORD_USER_ID")
    if mention and report.mention and user_id:
        # allowed_mentions whitelists exactly this user — guards against an
        # accidental @everyone if the copy ever contained one.
        body["content"] = f"<@{user_id}>"
        body["allowed_mentions"] = {"users": [user_id]}

    req = urllib.request.Request(
        webhook,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Discord's Cloudflare rules 403 the default "Python-urllib/X.Y".
            "User-Agent": "leetcode-nagger (https://github.com/, 2.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook returned {resp.status}")
