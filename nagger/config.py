"""Load and validate `config.yml`.

Behaviour lives here; secrets and anything that identifies you live in the
environment (see `nagger.notify`). Validation is deliberately noisy — a fork
with a typo'd cadence should fail on the first run, not silently nag on the
wrong days.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yml"

LIST_NAMES = {
    "blind75": "Blind 75",
    "neetcode150": "NeetCode 150",
    "neetcode250": "NeetCode 250",
}

WEEKDAY_NAMES = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

CADENCE_DAYS = {
    "daily": {0, 1, 2, 3, 4, 5, 6},
    "weekdays": {0, 1, 2, 3, 4},
    "no_sundays": {0, 1, 2, 3, 4, 5},
}

SMS_PROVIDERS = ("carrier_gateway", "twilio")

# number@gateway delivers a free SMS on most North American carriers.
CARRIER_GATEWAYS = {
    # US
    "att": "txt.att.net",
    "boost": "sms.myboostmobile.com",
    "cricket": "sms.cricketwireless.net",
    "googlefi": "msg.fi.google.com",
    "metropcs": "mymetropcs.com",
    "mint": "mailmymobile.net",
    "sprint": "messaging.sprintpcs.com",
    "tmobile": "tmomail.net",
    "uscellular": "email.uscc.net",
    "verizon": "vtext.com",
    "visible": "vtext.com",
    "xfinity": "vtext.com",
    # Canada
    "bell": "txt.bell.ca",
    "fido": "fido.ca",
    "freedom": "txt.freedommobile.ca",
    "koodo": "msg.telus.com",
    "rogers": "pcs.rogers.com",
    "telus": "msg.telus.com",
    "virgin": "vmobile.ca",
}


class ConfigError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"config.yml: {message}")


@dataclass(frozen=True)
class Schedule:
    cadence: str
    solve_days: frozenset[int]
    problems_per_day: int
    timezone: str
    nag_hour: int
    rest_day_review: bool

    def is_solve_day(self, day) -> bool:
        return day.weekday() in self.solve_days


@dataclass(frozen=True)
class Review:
    enabled: bool
    first_days: int
    second_days: int

    @property
    def gap_days(self) -> int:
        """Days between logging the first review and the second falling due."""
        return self.second_days - self.first_days


@dataclass(frozen=True)
class DiscordConfig:
    enabled: bool
    mention: bool


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    subject_prefix: str


@dataclass(frozen=True)
class SmsConfig:
    enabled: bool
    provider: str
    carrier: str

    @property
    def gateway(self) -> str:
        return CARRIER_GATEWAYS[self.carrier]


@dataclass(frozen=True)
class Channels:
    discord: DiscordConfig
    email: EmailConfig
    sms: SmsConfig

    @property
    def any_enabled(self) -> bool:
        return self.discord.enabled or self.email.enabled or self.sms.enabled


@dataclass(frozen=True)
class Config:
    list_key: str
    sheet_tab: str
    schedule: Schedule
    review: Review
    stop_when_complete: bool
    channels: Channels
    path: Path = field(default=DEFAULT_CONFIG_PATH, compare=False)

    @property
    def list_name(self) -> str:
        return LIST_NAMES.get(self.list_key, self.list_key)


def _section(data: dict, key: str) -> dict:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"`{key}:` must be a block of settings, got {type(value).__name__}.")
    return value


def _bool(data: dict, key: str, default: bool, where: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"`{where}{key}:` must be true or false, got {value!r}.")
    return value


def _int(data: dict, key: str, default: int, where: str, lo: int, hi: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"`{where}{key}:` must be a whole number, got {value!r}.")
    if not lo <= value <= hi:
        raise ConfigError(f"`{where}{key}:` must be between {lo} and {hi}, got {value}.")
    return value


def _solve_days(sched: dict) -> tuple[str, frozenset[int]]:
    cadence = str(sched.get("cadence", "weekdays")).strip().lower()
    if cadence in CADENCE_DAYS:
        return cadence, frozenset(CADENCE_DAYS[cadence])
    if cadence != "custom":
        options = ", ".join([*CADENCE_DAYS, "custom"])
        raise ConfigError(f"`schedule.cadence:` must be one of {options}, got {cadence!r}.")

    raw = sched.get("days") or []
    if not isinstance(raw, list) or not raw:
        raise ConfigError("`schedule.cadence: custom` needs a non-empty `schedule.days:` list.")
    days = set()
    for item in raw:
        key = str(item).strip().lower()
        if key not in WEEKDAY_NAMES:
            raise ConfigError(f"`schedule.days:` has an unknown day {item!r}. Use mon…sun.")
        days.add(WEEKDAY_NAMES[key])
    return cadence, frozenset(days)


def _validate_timezone(name: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ConfigError(
            f"`schedule.timezone:` {name!r} isn't a known IANA timezone "
            "(e.g. America/New_York, Europe/London, Asia/Tokyo)."
        ) from None
    return name


def load_config(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("NAGGER_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"not found at {path}. Copy `config.yml` from the repo root, or set "
            "NAGGER_CONFIG to point at yours."
        ) from None
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"is not valid YAML — {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError("must be a mapping of settings at the top level.")

    list_key = str(data.get("list", "blind75")).strip().lower()
    if list_key not in LIST_NAMES:
        raise ConfigError(
            f"`list:` must be one of {', '.join(LIST_NAMES)}, got {list_key!r}."
        )

    sched_raw = _section(data, "schedule")
    cadence, solve_days = _solve_days(sched_raw)
    schedule = Schedule(
        cadence=cadence,
        solve_days=solve_days,
        problems_per_day=_int(sched_raw, "problems_per_day", 1, "schedule.", 1, 20),
        timezone=_validate_timezone(str(sched_raw.get("timezone", "UTC")).strip()),
        nag_hour=_int(sched_raw, "nag_hour", 19, "schedule.", 0, 23),
        rest_day_review=_bool(sched_raw, "rest_day_review", True, "schedule."),
    )

    review_raw = _section(data, "review")
    review = Review(
        enabled=_bool(review_raw, "enabled", True, "review."),
        first_days=_int(review_raw, "first_days", 7, "review.", 1, 365),
        second_days=_int(review_raw, "second_days", 21, "review.", 2, 730),
    )
    if review.second_days <= review.first_days:
        raise ConfigError(
            f"`review.second_days:` ({review.second_days}) must be greater than "
            f"`review.first_days:` ({review.first_days})."
        )

    channels_raw = _section(data, "channels")
    discord_raw = _section(channels_raw, "discord")
    email_raw = _section(channels_raw, "email")
    sms_raw = _section(channels_raw, "sms")

    sms_provider = str(sms_raw.get("provider", "carrier_gateway")).strip().lower()
    sms_enabled = _bool(sms_raw, "enabled", False, "channels.sms.")
    if sms_enabled and sms_provider not in SMS_PROVIDERS:
        raise ConfigError(
            f"`channels.sms.provider:` must be one of {', '.join(SMS_PROVIDERS)}, "
            f"got {sms_provider!r}."
        )
    carrier = str(sms_raw.get("carrier", "")).strip().lower()
    if sms_enabled and sms_provider == "carrier_gateway" and carrier not in CARRIER_GATEWAYS:
        raise ConfigError(
            f"`channels.sms.carrier:` {carrier!r} isn't supported. Known carriers: "
            f"{', '.join(sorted(CARRIER_GATEWAYS))}."
        )

    channels = Channels(
        discord=DiscordConfig(
            enabled=_bool(discord_raw, "enabled", True, "channels.discord."),
            mention=_bool(discord_raw, "mention", True, "channels.discord."),
        ),
        email=EmailConfig(
            enabled=_bool(email_raw, "enabled", False, "channels.email."),
            subject_prefix=str(email_raw.get("subject_prefix", "[LeetCode]")).strip(),
        ),
        sms=SmsConfig(enabled=sms_enabled, provider=sms_provider, carrier=carrier),
    )
    if not channels.any_enabled:
        raise ConfigError("every channel is disabled — turn on at least one under `channels:`.")

    sheet_raw = _section(data, "sheet")
    return Config(
        list_key=list_key,
        sheet_tab=str(sheet_raw.get("tab", "") or "").strip(),
        schedule=schedule,
        review=review,
        stop_when_complete=_bool(data, "stop_when_complete", True, ""),
        channels=channels,
        path=path,
    )


def env(name: str, *, required: bool = False, hint: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        suffix = f" ({hint})" if hint else ""
        sys.exit(f"Missing required env var: {name}{suffix}")
    return value
