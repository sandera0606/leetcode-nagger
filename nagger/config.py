"""Load and validate `config.yml`.

Behaviour lives here; secrets and anything that identifies you live in the
environment (see `nagger.notify`). Validation is deliberately noisy — a fork
with a typo'd schedule should fail on the first run, not silently nag on the
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

# Shorthand for the common shapes. Anywhere a preset is accepted, an explicit
# list of days is too — `weekdays` and `[mon, tue, wed, thu, fri]` are the same
# setting written two ways.
DAY_PRESETS = {
    "daily": {0, 1, 2, 3, 4, 5, 6},
    "weekdays": {0, 1, 2, 3, 4},
    "weekends": {5, 6},
    "no_sundays": {0, 1, 2, 3, 4, 5},
    "none": set(),
}

class ConfigError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"config.yml: {message}")


@dataclass(frozen=True)
class Schedule:
    solve_days: frozenset[int]
    review_days: frozenset[int]
    problems_per_day: int
    timezone: str
    nag_hour: int

    def is_solve_day(self, day) -> bool:
        return day.weekday() in self.solve_days

    def is_review_day(self, day) -> bool:
        return day.weekday() in self.review_days


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
class Channels:
    discord: DiscordConfig
    email: EmailConfig

    @property
    def any_enabled(self) -> bool:
        return self.discord.enabled or self.email.enabled


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


def _days(value: object, where: str) -> frozenset[int]:
    """A set of weekdays, written either as a preset name or a list of days."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in DAY_PRESETS:
            return frozenset(DAY_PRESETS[key])
        raise ConfigError(
            f"`{where}:` {value!r} isn't a known preset. Use one of "
            f"{', '.join(DAY_PRESETS)}, or list the days: [mon, wed, fri]."
        )
    if isinstance(value, list):
        days = set()
        for item in value:
            key = str(item).strip().lower()
            if key not in WEEKDAY_NAMES:
                raise ConfigError(f"`{where}:` has an unknown day {item!r}. Use mon…sun.")
            days.add(WEEKDAY_NAMES[key])
        return frozenset(days)
    raise ConfigError(
        f"`{where}:` must be a list of days like [mon, wed, fri], or one of "
        f"{', '.join(DAY_PRESETS)}. Got {value!r}."
    )


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
    solve_days = _days(sched_raw.get("solve_days", "weekdays"), "schedule.solve_days")
    # Left out, review days are every day you aren't solving — the shape most
    # people want. Written explicitly (including `[]`), they're exactly that.
    review_raw_days = sched_raw.get("review_days", None)
    review_days = (
        frozenset(set(range(7)) - solve_days) if review_raw_days is None
        else _days(review_raw_days, "schedule.review_days")
    )
    if not solve_days and not review_days:
        raise ConfigError(
            "`schedule.solve_days:` and `schedule.review_days:` are both empty, "
            "so nothing would ever fire. Give at least one of them a day."
        )
    schedule = Schedule(
        solve_days=solve_days,
        review_days=review_days,
        problems_per_day=_int(sched_raw, "problems_per_day", 1, "schedule.", 1, 20),
        timezone=_validate_timezone(str(sched_raw.get("timezone", "UTC")).strip()),
        nag_hour=_int(sched_raw, "nag_hour", 19, "schedule.", 0, 23),
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

    channels = Channels(
        discord=DiscordConfig(
            enabled=_bool(discord_raw, "enabled", True, "channels.discord."),
            mention=_bool(discord_raw, "mention", True, "channels.discord."),
        ),
        email=EmailConfig(
            enabled=_bool(email_raw, "enabled", False, "channels.email."),
            subject_prefix=str(email_raw.get("subject_prefix", "[LeetCode]")).strip(),
        ),
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
