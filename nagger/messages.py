"""Copy pools and the channel-agnostic report the notifiers render.

`build_report` turns a `Status` into a `Report`: a title, a handful of
sections, and a footer. Each notifier renders that however its medium wants —
a rich embed, or an HTML email.

Light markdown (`**bold**`) is used in section lines; `plain()` strips it for
the media that can't show it.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date

from . import problems
from .tracker import Status

MAX_LISTED = 25       # a nag longer than this stops being read
FIELD_BUDGET = 1000   # Discord hard-caps a field value at 1024 chars

COLORS = {
    "overdue": 0xDC2626,   # red — overdue beats everything
    "new": 0xD97706,       # amber — cold attempt pending
    "rest": 0x2563EB,      # blue — review day
    "congrats": 0x059669,  # green
}

NEW_COLD_TITLES = [
    "Do a new cold attempt today.",
    "Pick a problem. Solve it. That's it.",
    "Today's tribute: one cold attempt.",
    "A wild LeetCode problem appears.",
    "Future-you is begging for one cold attempt.",
    "One problem. That's the whole ask.",
    "New cold attempt. Now. Yes, now.",
    "The schedule says: new problems today.",
    "Crack open LeetCode. Pick anything. Go.",
]

REST_DAY_TITLES = [
    "It's {day}. No new problems today.",
    "{day}. Time to re-read what you 'learned'.",
    "Review day. Yes, even when you don't feel like it.",
    "{day} means notes. Don't make excuses.",
    "It's notes-review day. Don't skim.",
]

REST_DAY_SUBTITLES = [
    "Re-read your notes on the {n} problem(s) you've cold-attempted.",
    "Open your notes for these {n} problem(s). All of them.",
    "{n} problem(s) need a refresher. Don't skim.",
    "Time to revisit {n} problem(s). Be thorough.",
]

REST_DAY_EMPTY_TITLES = [
    "It's {day}.",
    "{day}, and your tracker is bare.",
    "A suspiciously quiet {day}.",
]

REST_DAY_EMPTY_SUBTITLES = [
    "No cold attempts on record yet — start fresh on your next solve day.",
    "Nothing logged yet. Your next solve day is the fresh start.",
    "Empty tracker. Fix it on your next solve day.",
]

OVERDUE_FIRST_TITLES = [
    "{n} first review(s) overdue",
    "{n} problem(s) waiting to be re-solved — they're getting cold",
    "{n} first review(s) you've been avoiding",
    "{n} first review(s). Tick tock.",
    "{n} first review(s) aging in your tracker",
]

OVERDUE_SECOND_TITLES = [
    "{n} second review(s) overdue",
    "{n} second review(s) — the solutions are fading from your brain",
    "{n} second review(s). You barely remember solving these.",
    "{n} second review(s). Spaced repetition wants a word.",
    "{n} second review(s). Past-you would be disappointed.",
]

STREAK_TITLES_ALIVE = [
    "Streak: {n} day(s). Don't be the reason it ends.",
    "Streak: {n} day(s). Keep it alive.",
    "{n}-day streak. Don't blow it now.",
    "Streak holding: {n} day(s). One miss and it's gone.",
    "{n} days on streak. Future-you is proud. Don't ruin it.",
]

STREAK_TITLES_ZERO = [
    "Streak: 0. From the ashes, etc.",
    "No streak right now. Time to start one.",
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

MILESTONE_TITLES = [
    "{pct}% of {list_name}. Look at you.",
    "{pct}% done. I'm shocked. Pleasantly shocked.",
    "{pct}% of the way through {list_name}.",
    "Milestone: {pct}%. Ego: justified.",
    "{pct}% cleared. The interviewers are slightly less worried.",
]

MILESTONE_FOOTERS = [
    "Don't get cocky.",
    "Now do it again tomorrow.",
    "Sent silently because you've earned a moment of peace.",
    "No ping. You've earned the quiet.",
]

ALL_COLD_TITLES = [
    "All {total} problems cold-attempted. Now the reviews.",
    "{list_name}: every problem attempted once. Once isn't enough.",
    "{total}/{total} cold-attempted. Spaced repetition says: not so fast.",
    "You've touched all {total}. Reviews are the other half.",
    "Every problem in {list_name}, done once. Halfway, really.",
]

ALL_COLD_FOOTERS = [
    "Reviews are where it actually sticks.",
    "The fun part's done. The useful part isn't.",
    "Finish the reviews and I'll leave you alone for good.",
    "Don't stall at the finish line.",
]

COMPLETE_TITLES = [
    "{list_name}: complete. Every problem, every review.",
    "You finished {list_name}. Genuinely, well done.",
    "{list_name} is done. All {total} of them.",
]

COMPLETE_FOOTERS = [
    "Nothing left to nag about. Go outside.",
    "The nagging stops here. Enjoy it.",
    "Turn the cron off, or point it at a bigger list.",
]

MILESTONES = (25, 50, 75)


def pick(pool: list[str], **kw: object) -> str:
    return random.choice(pool).format(**kw)


# Masked links, the one piece of markdown Discord and email both understand.
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def unlink(text: str) -> str:
    """`[Two Sum](url)` -> `Two Sum`, for media that can't show a link."""
    return LINK_RE.sub(r"\1", text)


def linked(name: str) -> str:
    """Wrap a problem name in a link to its neetcode.io page, if we know it."""
    url = problems.url_for(name)
    return f"[{name}]({url})" if url else name


def plain(text: str) -> str:
    """Strip the light markdown used in section lines."""
    text = unlink(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"_(.+?)_", r"\1", text)


@dataclass
class Section:
    kind: str
    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Report:
    kind: str  # "nag" | "milestone" | "complete"
    title: str
    sections: list[Section]
    footer: str
    url: str
    day: date
    color: int
    mention: bool

    @property
    def pretty_date(self) -> str:
        return f"{self.day.strftime('%A')}, {self.day.strftime('%B')} {self.day.day}"


def _listing(items, formatter, used: int = 0) -> list[str]:
    """Format items into lines, stopping before the field-length cap.

    `used` is how much of the budget the caller has already spent on lines
    above the list. The trailing "…and N more" always fits — the reserve
    below is bigger than that line can ever be.
    """
    lines: list[str] = []
    budget = FIELD_BUDGET - used - 32
    for item in items:
        if len(lines) >= MAX_LISTED:
            break
        line = formatter(item)
        # Charge for what the tightest medium actually renders. Discord drops
        # the URL half of a masked link, so billing the full markdown would
        # shrink everyone's list to protect a limit that isn't being neared.
        cost = len(unlink(line))
        if budget - cost - 1 < 0:
            break
        lines.append(line)
        budget -= cost + 1
    extra = len(items) - len(lines)
    if extra > 0:
        lines.append(f"_…and {extra} more_")
    return lines


def build_report(status: Status, url: str, list_name: str, mention: bool) -> Report:
    sections: list[Section] = []

    if status.streak >= 1:
        sections.append(Section(
            "streak",
            pick(STREAK_TITLES_ALIVE, n=status.streak),
            [f"**{status.streak}**-day streak."],
        ))
    elif status.is_solve_day:
        sections.append(Section("streak", pick(STREAK_TITLES_ZERO), ["Streak: **0**."]))

    day_name = status.today.strftime("%A")
    if status.needs_new:
        left = status.quota - status.done_today
        detail = f"**{status.done_today}/{status.quota}** done today."
        if status.quota == 1:
            detail = "Nothing logged today yet."
        sections.append(Section("new", pick(NEW_COLD_TITLES), [
            detail,
            f"**{left}** to go · **{status.remaining}** left in {list_name}.",
        ]))
    elif status.is_review_day:
        if status.solved_names:
            subtitle = pick(REST_DAY_SUBTITLES, n=status.solved)
            sections.append(Section(
                "rest",
                pick(REST_DAY_TITLES, day=day_name),
                [subtitle] + _listing(
                    status.solved_names, lambda n: f"• {linked(n)}",
                    used=len(subtitle) + 1),
            ))
        else:
            sections.append(Section(
                "rest",
                pick(REST_DAY_EMPTY_TITLES, day=day_name),
                [pick(REST_DAY_EMPTY_SUBTITLES)],
            ))

    for kind, items, pool in (
        ("overdue", status.overdue_first, OVERDUE_FIRST_TITLES),
        ("overdue", status.overdue_second, OVERDUE_SECOND_TITLES),
    ):
        if not items:
            continue
        sections.append(Section(
            kind,
            pick(pool, n=len(items)),
            _listing(items, lambda d: (
                f"• **{linked(d.problem)}**"
                + (f" _({d.difficulty})_" if d.difficulty else "")
                + f" — **{d.days_overdue}d overdue**"
            )),
        ))

    kinds = {s.kind for s in sections}
    color = (
        COLORS["overdue"] if "overdue" in kinds
        else COLORS["new"] if "new" in kinds
        else COLORS["rest"]
    )
    return Report(
        kind="nag",
        title=f"LeetCode Nag · {status.today.strftime('%A')}, "
              f"{status.today.strftime('%B')} {status.today.day}",
        sections=sections,
        footer=pick(FOOTER_LINES),
        url=url,
        day=status.today,
        color=color,
        mention=mention,
    )


def build_milestone_report(status: Status, url: str, list_name: str, pct: int) -> Report:
    return Report(
        kind="milestone",
        title=pick(MILESTONE_TITLES, pct=pct, list_name=list_name),
        sections=[Section("congrats", "Progress", [
            f"**{status.solved}/{status.total}** cold-attempted.",
            f"**{status.streak}**-day streak.",
        ])],
        footer=pick(MILESTONE_FOOTERS),
        url=url,
        day=status.today,
        color=COLORS["congrats"],
        mention=False,  # celebrations shouldn't buzz your phone
    )


def build_all_cold_report(status: Status, url: str, list_name: str) -> Report:
    """Every problem attempted, reviews still outstanding.

    This window is guaranteed for everyone — the last problem's second review
    falls due weeks after its cold attempt — so it gets its own message rather
    than being lumped in with the percentage milestones.
    """
    left = status.pending_reviews
    return Report(
        kind="all-cold",
        title=pick(ALL_COLD_TITLES, list_name=list_name, total=status.total),
        sections=[Section("congrats", "Progress", [
            f"**{status.total}/{status.total}** problems cold-attempted.",
            f"**{left}** review(s) still to log.",
        ])],
        footer=pick(ALL_COLD_FOOTERS),
        url=url,
        day=status.today,
        color=COLORS["congrats"],
        mention=False,  # celebrations shouldn't buzz your phone
    )


def build_complete_report(status: Status, url: str, list_name: str) -> Report:
    return Report(
        kind="complete",
        title=pick(COMPLETE_TITLES, list_name=list_name, total=status.total),
        sections=[Section("congrats", "Final", [
            f"**{status.total}/{status.total}** problems cold-attempted.",
            "Every scheduled review logged.",
        ])],
        footer=pick(COMPLETE_FOOTERS),
        url=url,
        day=status.today,
        color=COLORS["congrats"],
        mention=False,
    )
