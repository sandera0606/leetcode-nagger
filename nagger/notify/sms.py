"""SMS delivery — free carrier email gateway, or Twilio.

`carrier_gateway` costs nothing and reuses the Gmail credentials: carriers
expose an address like 5551234567@vtext.com that turns an email into a text.
Delivery is best-effort and some carriers have quietly retired their gateway,
so if texts stop arriving, switch to `twilio`.
"""

from __future__ import annotations

import base64
import re
import urllib.error
import urllib.parse
import urllib.request

from ..config import SmsConfig, env
from ..messages import Report
from . import mail

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
MAX_LEN = 300


def normalize_number(raw: str) -> str:
    """Digits only, no country code — what carrier gateways expect."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def configured(cfg: SmsConfig) -> bool:
    if not env("SMS_TO"):
        return False
    if cfg.provider == "twilio":
        return bool(env("TWILIO_ACCOUNT_SID") and env("TWILIO_AUTH_TOKEN") and env("TWILIO_FROM"))
    return mail.configured()


def send(report: Report, cfg: SmsConfig) -> None:
    to = env("SMS_TO", required=True, hint="your mobile number, e.g. +15551234567")
    body = report.sms[:MAX_LEN]
    if cfg.provider == "twilio":
        _send_twilio(to, body)
    else:
        _send_gateway(to, body, cfg.gateway)


def _send_gateway(to: str, body: str, gateway: str) -> None:
    number = normalize_number(to)
    if len(number) != 10:
        raise RuntimeError(
            f"SMS_TO {to!r} doesn't look like a 10-digit North American number, "
            "which is all the carrier gateways accept. Use provider: twilio for "
            "anything else."
        )
    # Most gateways prepend the subject to the text; an empty one keeps it clean.
    mail.deliver([f"{number}@{gateway}"], "", body)


def _send_twilio(to: str, body: str) -> None:
    sid = env("TWILIO_ACCOUNT_SID", required=True, hint="from the Twilio console")
    token = env("TWILIO_AUTH_TOKEN", required=True, hint="from the Twilio console")
    sender = env("TWILIO_FROM", required=True, hint="your Twilio number, e.g. +15550001111")

    data = urllib.parse.urlencode({"From": sender, "To": to, "Body": body}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(
        TWILIO_API.format(sid=urllib.parse.quote(sid)),
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"Twilio returned {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Twilio returned {exc.code}: {detail}") from None
