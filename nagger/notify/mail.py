"""Email delivery over SMTP — Gmail by default.

Gmail needs an *App Password*, not your account password: turn on 2-Step
Verification, then myaccount.google.com/apppasswords. Point SMTP_HOST /
SMTP_PORT elsewhere if you'd rather not use Gmail.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from ..config import env
from ..messages import Report, plain

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587


def credentials() -> tuple[str, str, str, int]:
    user = env(
        "GMAIL_ADDRESS",
        required=True,
        hint="the Gmail account the nags are sent *from*",
    )
    password = env(
        "GMAIL_APP_PASSWORD",
        required=True,
        hint="a Google App Password, not your normal password",
    )
    host = env("SMTP_HOST") or DEFAULT_HOST
    port_raw = env("SMTP_PORT")
    port = int(port_raw) if port_raw.isdigit() else DEFAULT_PORT
    return user, password, host, port


def configured() -> bool:
    return bool(env("GMAIL_ADDRESS") and env("GMAIL_APP_PASSWORD"))


def deliver(to: list[str], subject: str, text: str, html: str | None = None) -> None:
    """Low-level send. Also used by the carrier-gateway SMS channel."""
    user, password, host, port = credentials()

    msg = EmailMessage()
    msg["From"] = formataddr(("LeetCode Nagger", user))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.login(user, password)
        smtp.send_message(msg)


def render_text(report: Report) -> str:
    parts = [report.title, "=" * len(report.title), ""]
    for section in report.sections:
        parts.append(plain(section.title))
        parts.extend(plain(line) for line in section.lines)
        parts.append("")
    parts.append(report.footer)
    parts.append("")
    parts.append(f"Tracker: {report.url}")
    return "\n".join(parts)


def render_html(report: Report) -> str:
    accent = f"#{report.color:06X}"
    blocks = []
    for section in report.sections:
        items = "".join(
            f'<div style="margin:2px 0;color:#374151;">{_inline(line)}</div>'
            for line in section.lines
        )
        blocks.append(
            '<div style="margin:0 0 18px;">'
            f'<div style="font-weight:600;color:#111827;margin-bottom:4px;">'
            f"{_inline(section.title)}</div>{items}</div>"
        )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,'
        'Arial,sans-serif;font-size:15px;line-height:1.5;max-width:560px;">'
        f'<div style="border-left:4px solid {accent};padding:16px 18px;'
        'background:#F9FAFB;border-radius:6px;">'
        f'<div style="font-size:17px;font-weight:700;color:#111827;'
        f'margin-bottom:16px;">{_escape(report.title)}</div>'
        f'{"".join(blocks)}'
        f'<div style="color:#6B7280;font-style:italic;">{_escape(report.footer)}</div>'
        "</div>"
        f'<p style="margin-top:16px;"><a href="{_escape(report.url)}" '
        f'style="color:{accent};">Open your tracker →</a></p></div>'
    )


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(text: str) -> str:
    """Escape, then turn the light markdown into HTML."""
    out = _escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"_(.+?)_", r"<em>\1</em>", out)
    return out


def send(report: Report, subject_prefix: str) -> None:
    recipients = [
        addr.strip() for addr in env(
            "EMAIL_TO",
            required=True,
            hint="where the nags go; comma-separate for more than one",
        ).split(",") if addr.strip()
    ]
    subject = " ".join(filter(None, [subject_prefix, report.title]))
    deliver(recipients, subject, render_text(report), render_html(report))
