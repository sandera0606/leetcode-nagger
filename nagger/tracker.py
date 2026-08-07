"""Read the tracker tab and work out what's due.

The sheet is the source of truth — there is no database. Every question the
nagger asks ("am I behind?", "what reviews are overdue?", "what's my streak?")
is derived from three date columns.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import Config, Schedule

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
)

# Google Sheets stores dates as days since 1899-12-30. If a cell is formatted
# as a plain number we get the serial back instead of a date string.
SHEETS_EPOCH = date(1899, 12, 30)
SERIAL_MIN, SERIAL_MAX = 25_569, 80_000  # ~1970 to ~2119


def parse_date(cell: str) -> date | None:
    cell = (cell or "").strip()
    if not cell:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cell, fmt).date()
        except ValueError:
            continue
    try:
        serial = float(cell)
    except ValueError:
        return None
    if SERIAL_MIN <= serial <= SERIAL_MAX:
        return SHEETS_EPOCH + timedelta(days=int(serial))
    return None


def norm(s: str) -> str:
    return (s or "").strip().lower()


@dataclass
class ProblemRow:
    problem: str
    difficulty: str
    cold: date | None
    first_review: date | None
    second_review: date | None


@dataclass
class DueItem:
    problem: str
    difficulty: str
    days_overdue: int


@dataclass
class Status:
    """Everything the message layer needs, already decided."""
    today: date
    is_solve_day: bool
    total: int
    solved: int
    remaining: int
    done_today: int
    quota: int
    needs_new: bool
    overdue_first: list[DueItem]
    overdue_second: list[DueItem]
    solved_names: list[str]
    streak: int
    all_cold_done: bool
    all_reviews_done: bool

    @property
    def has_overdue(self) -> bool:
        return bool(self.overdue_first or self.overdue_second)

    @property
    def complete(self) -> bool:
        return self.all_cold_done and self.all_reviews_done

    @property
    def percent(self) -> int:
        return round(100 * self.solved / self.total) if self.total else 0


# ---- header discovery ---------------------------------------------------

def _match_column(header: str) -> str | None:
    h = norm(header)
    if not h:
        return None
    if h == "problem" or h.startswith("problem"):
        return "problem"
    if h in ("diff", "difficulty"):
        return "difficulty"
    if "cold" in h:
        return "cold"
    # "1wk Review", "1 wk", "1 week", "first review"
    if any(t in h for t in ("1wk", "1 wk", "1 week", "first review")):
        return "first"
    if any(t in h for t in ("3wk", "3 wk", "3 week", "second review")):
        return "second"
    return None


# Difficulty is the only column the nagger can do without.
REQUIRED_COLUMNS = ("problem", "cold", "first", "second")

COLUMN_LABELS = {
    "problem": "'Problem'",
    "cold": "'Cold ✓ (date)'",
    "first": "'1wk Review'",
    "second": "'3wk Review'",
}


def find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Find the real header row, skipping any dashboard block above it."""
    best: dict[str, int] = {}
    for i, row in enumerate(rows):
        cols: dict[str, int] = {}
        for j, cell in enumerate(row):
            key = _match_column(cell)
            if key and key not in cols:
                cols[key] = j
        if set(REQUIRED_COLUMNS).issubset(cols):
            return i, cols
        # Remember the closest near-miss so the error can name what's absent.
        if len(cols) > len(best):
            best = cols

    missing = [COLUMN_LABELS[c] for c in REQUIRED_COLUMNS if c not in best]
    detail = (
        f"Found a header row but it's missing {', '.join(missing)}."
        if best else
        "No header row looked like a tracker at all."
    )
    sys.exit(
        f"Couldn't read the tracker. {detail}\n"
        f"The tab needs all of: {', '.join(COLUMN_LABELS[c] for c in REQUIRED_COLUMNS)}. "
        "Matching is case-insensitive and loose ('Cold attempt', 'First review', "
        "'1 week review' all work). Check that `sheet.tab` in config.yml names "
        "the right tab, and start from a sheet in templates/ if in doubt."
    )


def parse_rows(rows: list[list[str]], cols: dict[str, int]) -> list[ProblemRow]:
    width = max(cols.values()) + 1
    out: list[ProblemRow] = []

    def cell(row: list[str], key: str) -> str:
        idx = cols.get(key)
        return row[idx] if idx is not None else ""

    for row in rows:
        if not row or not any(c.strip() for c in row):
            continue
        padded = list(row) + [""] * (width - len(row))
        problem = padded[cols["problem"]].strip()
        if not problem:
            continue
        out.append(ProblemRow(
            problem=problem,
            difficulty=cell(padded, "difficulty").strip(),
            cold=parse_date(padded[cols["cold"]]),
            first_review=parse_date(cell(padded, "first")),
            second_review=parse_date(cell(padded, "second")),
        ))
    return out


# ---- streak -------------------------------------------------------------

def compute_streak(problems: list[ProblemRow], today: date, schedule: Schedule) -> int:
    """Consecutive solve days, walking backwards, where you logged at least
    `problems_per_day` cold attempts. Rest days are skipped, not broken.

    Today only counts once you've met the quota — a day you haven't done yet
    shouldn't read as a broken streak at 7pm.
    """
    per_day = Counter(p.cold for p in problems if p.cold)
    if not per_day:
        return 0
    earliest = min(per_day)
    quota = schedule.problems_per_day

    day = today
    if schedule.is_solve_day(day) and per_day[day] < quota:
        day -= timedelta(days=1)

    streak = 0
    while day >= earliest:
        if not schedule.is_solve_day(day):
            day -= timedelta(days=1)
            continue
        if per_day[day] < quota:
            break
        streak += 1
        day -= timedelta(days=1)
    return streak


# ---- status -------------------------------------------------------------

def build_status(problems: list[ProblemRow], today: date, cfg: Config) -> Status:
    review = cfg.review
    schedule = cfg.schedule

    overdue_first: list[DueItem] = []
    overdue_second: list[DueItem] = []
    solved_names: list[str] = []
    done_today = 0
    pending_reviews = 0

    for p in problems:
        if p.cold:
            solved_names.append(p.problem)
            if p.cold == today:
                done_today += 1

        if not review.enabled or not p.cold:
            continue

        if not p.first_review:
            pending_reviews += 1
            due = p.cold + timedelta(days=review.first_days)
            if today >= due:
                overdue_first.append(DueItem(p.problem, p.difficulty, (today - due).days))
        elif not p.second_review:
            pending_reviews += 1
            due = p.first_review + timedelta(days=review.gap_days)
            if today >= due:
                overdue_second.append(DueItem(p.problem, p.difficulty, (today - due).days))

    overdue_first.sort(key=lambda d: -d.days_overdue)
    overdue_second.sort(key=lambda d: -d.days_overdue)

    total = len(problems)
    solved = len(solved_names)
    remaining = total - solved
    is_solve_day = schedule.is_solve_day(today)
    quota = schedule.problems_per_day
    needs_new = is_solve_day and remaining > 0 and done_today < quota

    return Status(
        today=today,
        is_solve_day=is_solve_day,
        total=total,
        solved=solved,
        remaining=remaining,
        done_today=done_today,
        quota=quota,
        needs_new=needs_new,
        overdue_first=overdue_first,
        overdue_second=overdue_second,
        solved_names=solved_names,
        streak=compute_streak(problems, today, schedule),
        all_cold_done=total > 0 and remaining == 0,
        all_reviews_done=pending_reviews == 0,
    )
