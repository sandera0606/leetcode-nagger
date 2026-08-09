"""Offline tests — no Google, no Discord, no SMTP.

    python -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nagger.config import Channels, Config, DiscordConfig, EmailConfig, Review, Schedule
from nagger.config import ConfigError, load_config
from nagger.messages import (
    MILESTONES,
    build_all_cold_report,
    build_complete_report,
    build_milestone_report,
    build_report,
    plain,
    unlink,
)
from nagger import notify, problems, sheets
from nagger.state import State
from nagger.notify import discord, mail
from nagger.tracker import ProblemRow, build_status, compute_streak, find_header, parse_date, parse_rows

TODAY = date(2026, 8, 7)  # a Friday


def make_config(**overrides) -> Config:
    solve_days = frozenset(overrides.pop("solve_days", {0, 1, 2, 3, 4}))
    schedule = Schedule(
        solve_days=solve_days,
        review_days=frozenset(overrides.pop("review_days", set(range(7)) - solve_days)),
        problems_per_day=overrides.pop("problems_per_day", 1),
        timezone="America/New_York",
        nag_hour=19,
    )
    review = Review(
        enabled=overrides.pop("review_enabled", True),
        first_days=overrides.pop("first_days", 7),
        second_days=overrides.pop("second_days", 21),
    )
    channels = Channels(
        discord=DiscordConfig(enabled=True, mention=True),
        email=EmailConfig(enabled=False, subject_prefix="[LeetCode]"),
    )
    return Config(
        list_key="blind75",
        sheet_tab="Tracker",
        schedule=schedule,
        review=review,
        stop_when_complete=overrides.pop("stop_when_complete", True),
        channels=channels,
    )


class TestParseDate(unittest.TestCase):
    def test_common_formats(self):
        for text in ("2026-05-20", "2026/05/20", "05/20/2026", "2026-05-20 00:00:00",
                     "May 20, 2026"):
            self.assertEqual(parse_date(text), date(2026, 5, 20), text)

    def test_sheets_serial(self):
        # 2026-05-20 is 46157 days after the 1899-12-30 epoch.
        self.assertEqual(parse_date("46162"), date(2026, 5, 20))

    def test_blank_and_junk(self):
        for text in ("", "   ", "n/a", "soon", None):
            self.assertIsNone(parse_date(text))

    def test_small_numbers_are_not_dates(self):
        self.assertIsNone(parse_date("3"))


class TestHeader(unittest.TestCase):
    ROWS = [
        ["Blind 75 — Tracker"],
        ["DASHBOARD"],
        ["Total problems", "Cold ✓"],
        ["=75", "=COUNTA(G8:G82)"],
        [],
        ["#", "Pattern", "Problem", "Diff", "Time Budget", "Link",
         "Cold ✓ (date)", "1wk Review", "3wk Review", "Key Insight + Pitfall", "Confidence"],
        ["1", "Arrays & Hashing", "Contains Duplicate", "Easy", "", "", "2026-08-01", "", ""],
    ]

    def test_skips_dashboard(self):
        idx, cols = find_header(self.ROWS)
        self.assertEqual(idx, 5)
        self.assertEqual(cols["problem"], 2)
        self.assertEqual(cols["cold"], 6)
        self.assertEqual(cols["first"], 7)
        self.assertEqual(cols["second"], 8)

    def test_parses_rows_and_pads_short_ones(self):
        idx, cols = find_header(self.ROWS)
        rows = parse_rows(self.ROWS[idx + 1:], cols)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].problem, "Contains Duplicate")
        self.assertEqual(rows[0].cold, date(2026, 8, 1))
        self.assertIsNone(rows[0].first_review)

    def test_alternate_header_wording(self):
        rows = [["Problem", "Difficulty", "Cold attempt", "First review", "Second review"]]
        _, cols = find_header(rows)
        self.assertEqual(set(cols), {"problem", "difficulty", "cold", "first", "second"})

    def test_difficulty_stays_optional(self):
        rows = [["Problem", "Cold ✓ (date)", "1wk Review", "3wk Review"]]
        _, cols = find_header(rows)
        self.assertNotIn("difficulty", cols)

    def test_review_columns_are_required(self):
        rows = [["Problem", "Diff", "Cold ✓ (date)"]]
        with self.assertRaises(SystemExit) as ctx:
            find_header(rows)
        message = str(ctx.exception)
        self.assertIn("1wk Review", message)
        self.assertIn("3wk Review", message)

    def test_error_names_only_the_missing_column(self):
        rows = [["Problem", "Diff", "Cold ✓ (date)", "1wk Review"]]
        with self.assertRaises(SystemExit) as ctx:
            find_header(rows)
        message = str(ctx.exception)
        self.assertIn("missing '3wk Review'", message)
        self.assertNotIn("missing '1wk Review'", message)

    def test_missing_columns_exits(self):
        with self.assertRaises(SystemExit):
            find_header([["Name", "Notes"]])


class TestStreak(unittest.TestCase):
    def solved_on(self, *days: date) -> list[ProblemRow]:
        return [ProblemRow(f"P{i}", "Easy", d, None, None) for i, d in enumerate(days)]

    def test_weekday_cadence_skips_the_weekend(self):
        cfg = make_config()
        # Wed, Thu, Fri last week, then Mon–Thu this week; today is Friday.
        days = [date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31),
                date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6)]
        self.assertEqual(compute_streak(self.solved_on(*days), TODAY, cfg.schedule), 7)

    def test_today_pending_does_not_break_it(self):
        cfg = make_config()
        streak = compute_streak(self.solved_on(date(2026, 8, 6)), TODAY, cfg.schedule)
        self.assertEqual(streak, 1)

    def test_today_counts_once_done(self):
        cfg = make_config()
        rows = self.solved_on(date(2026, 8, 6), TODAY)
        self.assertEqual(compute_streak(rows, TODAY, cfg.schedule), 2)

    def test_missed_solve_day_breaks_it(self):
        cfg = make_config()
        # Skipped Thursday the 6th.
        rows = self.solved_on(date(2026, 8, 4), date(2026, 8, 5))
        self.assertEqual(compute_streak(rows, TODAY, cfg.schedule), 0)

    def test_quota_of_two_needs_two_a_day(self):
        cfg = make_config(problems_per_day=2)
        one_each = self.solved_on(date(2026, 8, 5), date(2026, 8, 6))
        self.assertEqual(compute_streak(one_each, TODAY, cfg.schedule), 0)
        two_each = self.solved_on(date(2026, 8, 5), date(2026, 8, 5),
                                  date(2026, 8, 6), date(2026, 8, 6))
        self.assertEqual(compute_streak(two_each, TODAY, cfg.schedule), 2)

    def test_empty_tracker(self):
        self.assertEqual(compute_streak([], TODAY, make_config().schedule), 0)


class TestStatus(unittest.TestCase):
    def test_overdue_first_review(self):
        cfg = make_config()
        rows = [ProblemRow("Two Sum", "Easy", TODAY - timedelta(days=10), None, None)]
        status = build_status(rows, TODAY, cfg)
        self.assertEqual(len(status.overdue_first), 1)
        self.assertEqual(status.overdue_first[0].days_overdue, 3)
        self.assertFalse(status.overdue_second)

    def test_second_review_is_relative_to_the_first(self):
        cfg = make_config()
        rows = [ProblemRow("Two Sum", "Easy", TODAY - timedelta(days=40),
                           TODAY - timedelta(days=20), None)]
        status = build_status(rows, TODAY, cfg)
        self.assertFalse(status.overdue_first)
        self.assertEqual(status.overdue_second[0].days_overdue, 6)  # 20 - 14

    def test_finished_problem_is_never_overdue(self):
        cfg = make_config()
        rows = [ProblemRow("Two Sum", "Easy", date(2020, 1, 1), date(2020, 1, 8), date(2020, 2, 1))]
        status = build_status(rows, TODAY, cfg)
        self.assertFalse(status.has_overdue)
        self.assertTrue(status.all_reviews_done)

    def test_reviews_disabled(self):
        cfg = make_config(review_enabled=False)
        rows = [ProblemRow("Two Sum", "Easy", date(2020, 1, 1), None, None)]
        status = build_status(rows, TODAY, cfg)
        self.assertFalse(status.has_overdue)
        self.assertTrue(status.all_reviews_done)

    def test_needs_new_on_a_solve_day(self):
        cfg = make_config()
        rows = [ProblemRow("A", "Easy", None, None, None),
                ProblemRow("B", "Easy", TODAY - timedelta(days=1), None, None)]
        status = build_status(rows, TODAY, cfg)
        self.assertTrue(status.needs_new)
        self.assertEqual(status.remaining, 1)
        self.assertEqual(status.percent, 50)

    def test_no_new_once_todays_quota_is_met(self):
        cfg = make_config()
        rows = [ProblemRow("A", "Easy", TODAY, None, None), ProblemRow("B", "Easy", None, None, None)]
        self.assertFalse(build_status(rows, TODAY, cfg).needs_new)

    def test_no_new_on_a_rest_day(self):
        cfg = make_config()
        saturday = date(2026, 8, 8)
        rows = [ProblemRow("A", "Easy", None, None, None)]
        status = build_status(rows, saturday, cfg)
        self.assertFalse(status.is_solve_day)
        self.assertFalse(status.needs_new)

    def test_no_sundays_cadence(self):
        cfg = make_config(solve_days={0, 1, 2, 3, 4, 5})
        rows = [ProblemRow("A", "Easy", None, None, None)]
        self.assertTrue(build_status(rows, date(2026, 8, 8), cfg).is_solve_day)   # Sat
        self.assertFalse(build_status(rows, date(2026, 8, 9), cfg).is_solve_day)  # Sun

    def test_complete(self):
        cfg = make_config()
        rows = [ProblemRow("A", "Easy", date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 22))]
        status = build_status(rows, TODAY, cfg)
        self.assertTrue(status.complete)
        self.assertEqual(status.percent, 100)
        self.assertFalse(status.needs_new)


class TestReports(unittest.TestCase):
    def status(self, **kw):
        cfg = make_config()
        rows = kw.pop("rows", [
            ProblemRow("Two Sum", "Easy", TODAY - timedelta(days=30), None, None),
            ProblemRow("3Sum", "Medium", TODAY - timedelta(days=2), None, None),
            ProblemRow("Word Break", "Medium", None, None, None),
        ])
        return build_status(rows, TODAY, cfg)

    def test_nag_has_sections(self):
        report = build_report(self.status(), "https://example.com", "Blind 75", mention=True)
        self.assertTrue(report.sections)
        kinds = {s.kind for s in report.sections}
        self.assertIn("new", kinds)
        self.assertIn("overdue", kinds)

    def test_long_lists_are_trimmed(self):
        rows = [ProblemRow(f"Problem {i}", "Easy", TODAY - timedelta(days=30), None, None)
                for i in range(60)]
        report = build_report(self.status(rows=rows), "https://example.com", "Blind 75", True)
        overdue = next(s for s in report.sections if s.kind == "overdue")
        listed = len(overdue.lines) - 1  # last line is the "…and N more" tail
        self.assertIn(f"and {60 - listed} more", plain(overdue.body))
        self.assertLessEqual(len(overdue.body), 1024)

    def test_rest_day_list_also_fits_the_field(self):
        cfg = make_config()
        rows = [ProblemRow(f"A Fairly Long Problem Name {i}", "Easy",
                           date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7))
                for i in range(200)]
        status = build_status(rows, date(2026, 8, 8), cfg)  # Saturday
        report = build_report(status, "https://example.com", "Blind 75", True)
        rest = next(s for s in report.sections if s.kind == "rest")
        self.assertLessEqual(len(rest.body), 1024)
        self.assertIn("more", rest.lines[-1])

    def test_rest_day_lists_notes(self):
        cfg = make_config()
        rows = [ProblemRow("Two Sum", "Easy", date(2026, 8, 5), date(2026, 8, 6), None)]
        status = build_status(rows, date(2026, 8, 8), cfg)  # Saturday
        report = build_report(status, "https://example.com", "Blind 75", True)
        self.assertIn("rest", {s.kind for s in report.sections})

    def test_email_rendering_is_escaped_and_bolded(self):
        report = build_report(self.status(), "https://example.com", "Blind 75", True)
        html = mail.render_html(report)
        text = mail.render_text(report)
        self.assertIn("<strong>", html)
        self.assertNotIn("**", text)
        self.assertIn("https://example.com", text)

    def test_html_escapes_problem_names(self):
        rows = [ProblemRow("A < B & C", "Easy", TODAY - timedelta(days=30), None, None)]
        report = build_report(self.status(rows=rows), "https://example.com", "Blind 75", True)
        html = mail.render_html(report)
        self.assertIn("A &lt; B &amp; C", html)

    def test_celebrations_never_mention(self):
        status = self.status()
        for report in (build_milestone_report(status, "u", "Blind 75", 50),
                       build_all_cold_report(status, "u", "Blind 75"),
                       build_complete_report(status, "u", "Blind 75")):
            self.assertFalse(report.mention)


class TestCelebrationChoice(unittest.TestCase):
    """Which celebration fires for a given state.

    Everyone passes through "every problem attempted, reviews outstanding" —
    the last problem's second review isn't due until weeks after its cold
    attempt. At that point `percent` is 100, which clears every milestone
    threshold, so picking the highest one announces 75% over a 75/75 body.
    """

    def _pick(self, status):
        """The branch order from nag.py."""
        if status.complete:
            return "complete"
        if status.all_cold_done:
            return "all-cold"
        reached = [m for m in MILESTONES if status.percent >= m]
        return f"milestone:{max(reached)}" if reached else None

    def _rows(self, n, cold, first=None, second=None):
        return [ProblemRow(f"P{i}", "Easy", cold, first, second) for i in range(n)]

    def status(self, rows):
        return build_status(rows, TODAY, make_config())

    def test_all_cold_with_reviews_pending_is_not_a_milestone(self):
        cold = TODAY - timedelta(days=60)
        status = self.status(self._rows(75, cold))
        self.assertEqual(status.percent, 100)
        self.assertTrue(status.all_cold_done)
        self.assertFalse(status.complete)
        self.assertEqual(self._pick(status), "all-cold")

    def test_all_cold_report_counts_outstanding_reviews(self):
        cold = TODAY - timedelta(days=60)
        status = self.status(self._rows(75, cold))
        self.assertEqual(status.pending_reviews, 75)
        report = build_all_cold_report(status, "u", "Blind 75")
        self.assertIn("75", report.sections[0].lines[1])

    def test_everything_logged_is_complete(self):
        cold = TODAY - timedelta(days=60)
        rows = self._rows(75, cold, cold + timedelta(days=7), cold + timedelta(days=21))
        status = self.status(rows)
        self.assertEqual(status.pending_reviews, 0)
        self.assertEqual(self._pick(status), "complete")

    def test_partial_progress_still_uses_milestones(self):
        cold = TODAY - timedelta(days=60)
        rows = self._rows(40, cold) + [ProblemRow(f"X{i}", "Easy", None, None, None)
                                       for i in range(35)]
        status = self.status(rows)
        self.assertFalse(status.all_cold_done)
        self.assertEqual(self._pick(status), "milestone:50")


class TestProblemLinks(unittest.TestCase):
    """Email links each problem to its neetcode.io page.

    The slug is not derivable from the name — 'Contains Duplicate' lives at
    /duplicate-integer — so this leans on data/problems.json, the same file
    the shipped templates build their Link column from.
    """

    def status(self, names):
        cold = TODAY - timedelta(days=30)
        rows = [ProblemRow(n, "Easy", cold, None, None) for n in names]
        return build_status(rows, TODAY, make_config())

    def report(self, names=("Contains Duplicate",)):
        return build_report(self.status(names), "https://sheet", "Blind 75", True)

    def test_slug_lookup_is_not_the_name(self):
        self.assertEqual(problems.url_for("Contains Duplicate"),
                         "https://neetcode.io/problems/duplicate-integer")

    def test_lookup_tolerates_spreadsheet_mangling(self):
        for variant in ("contains duplicate", "  Contains  Duplicate ", "Contains-Duplicate"):
            self.assertEqual(problems.url_for(variant),
                             problems.url_for("Contains Duplicate"), variant)

    def test_unknown_names_get_no_link(self):
        self.assertEqual(problems.url_for("Some Problem I Invented"), "")

    def test_email_html_links_the_problem(self):
        html = mail.render_html(self.report())
        self.assertIn('href="https://neetcode.io/problems/duplicate-integer"', html)
        self.assertIn("Open your tracker", html)  # the tracker link stays

    def test_email_plain_text_has_no_markdown_left(self):
        text = mail.render_text(self.report())
        self.assertIn("Contains Duplicate", text)
        self.assertNotIn("](", text)
        self.assertNotIn("https://neetcode.io", text)

    def test_discord_field_carries_no_url(self):
        report = self.report()
        for section in report.sections:
            self.assertNotIn("neetcode.io", unlink(section.body))

    def test_unknown_problem_renders_without_breaking(self):
        html = mail.render_html(self.report(("Totally Made Up Problem",)))
        self.assertIn("Totally Made Up Problem", html)
        self.assertNotIn("](", html)

    def test_listing_budget_ignores_url_length(self):
        """Links must not shrink how many problems get listed."""
        many = [f"Problem Number {i}" for i in range(75)]
        unlinked = len([l for l in self.report(many).sections[0].lines if l.startswith("•")])
        with mock.patch.object(problems, "url_for",
                               return_value="https://neetcode.io/problems/x" + "y" * 40):
            linked_count = len([l for l in self.report(many).sections[0].lines
                                if l.startswith("•")])
        self.assertEqual(unlinked, linked_count)


class TestDispatch(unittest.TestCase):
    """One misconfigured channel must never take the others down."""

    def setUp(self):
        # dispatch narrates each channel's outcome. Under `unittest discover`
        # that lands in the terminal as "discord: sent", which reads like the
        # suite just messaged someone.
        quiet = contextlib.ExitStack()
        sink = io.StringIO()
        quiet.enter_context(contextlib.redirect_stdout(sink))
        quiet.enter_context(contextlib.redirect_stderr(sink))
        self.addCleanup(quiet.close)
        self._env = dict(os.environ)
        for key in ("EMAIL_TO", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                    "DISCORD_WEBHOOK_URL"):
            os.environ.pop(key, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        rows = [ProblemRow("Two Sum", "Easy", None, None, None)]
        self.report = build_report(
            build_status(rows, TODAY, make_config()), "u", "Blind 75", True)

    def channels(self, **kw):
        return Channels(
            discord=DiscordConfig(enabled=kw.get("discord", True), mention=True),
            email=EmailConfig(enabled=kw.get("email", False), subject_prefix="[LC]"),
        )

    def test_email_without_recipient_is_skipped_not_fatal(self):
        os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/x"
        os.environ["GMAIL_ADDRESS"] = "me@gmail.com"
        os.environ["GMAIL_APP_PASSWORD"] = "pw"
        with mock.patch.object(discord, "send"):
            results = notify.dispatch(self.report, self.channels(email=True))
        self.assertEqual(results["discord"], "sent")
        self.assertTrue(results["email"].startswith("skipped"))
        self.assertIn("EMAIL_TO", results["email"])

    def test_a_sender_calling_sys_exit_cannot_abort_the_run(self):
        os.environ.update({"DISCORD_WEBHOOK_URL": "https://x", "GMAIL_ADDRESS": "me@g.com",
                           "GMAIL_APP_PASSWORD": "pw", "EMAIL_TO": "me@g.com"})
        with mock.patch.object(mail, "send", side_effect=SystemExit("boom")), \
             mock.patch.object(discord, "send"):
            results = notify.dispatch(self.report, self.channels(email=True))
        self.assertEqual(results["discord"], "sent")
        self.assertTrue(results["email"].startswith("failed"))
        self.assertTrue(notify.any_failed(results))
        self.assertTrue(notify.any_sent(results))

    def test_one_channel_failing_still_sends_the_others(self):
        os.environ.update({"DISCORD_WEBHOOK_URL": "https://x", "GMAIL_ADDRESS": "me@g.com",
                           "GMAIL_APP_PASSWORD": "pw", "EMAIL_TO": "me@g.com"})
        with mock.patch.object(discord, "send", side_effect=RuntimeError("403")), \
             mock.patch.object(mail, "send"):
            results = notify.dispatch(self.report, self.channels(email=True))
        self.assertTrue(results["discord"].startswith("failed"))
        self.assertEqual(results["email"], "sent")

    def test_disabled_channels_are_absent(self):
        os.environ["DISCORD_WEBHOOK_URL"] = "https://x"
        with mock.patch.object(discord, "send"):
            results = notify.dispatch(self.report, self.channels())
        self.assertEqual(set(results), {"discord"})


class TestDiscordPayload(unittest.TestCase):
    """What actually goes over the wire. Discord 400s on an oversized embed,
    and a rejected payload means a silently missed nag."""

    def setUp(self):
        self._env = dict(os.environ)
        os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/x"
        os.environ["DISCORD_USER_ID"] = "614843209872"
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def capture(self, report, mention=True) -> dict:
        seen = {}

        class Resp:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["req"] = req
            return Resp()

        with mock.patch.object(discord.urllib.request, "urlopen", fake_urlopen):
            discord.send(report, mention)
        import json
        return json.loads(seen["req"].data.decode("utf-8"))

    def overloaded_report(self):
        """Every problem attempted, no reviews logged — 75 overdue at once.
        This is a state every user reaches, not a contrived one."""
        cold = TODAY - timedelta(days=60)
        rows = [ProblemRow(f"Some Fairly Long Problem Name {i}", "Medium", cold, None, None)
                for i in range(75)]
        return build_report(build_status(rows, TODAY, make_config()), "u", "Blind 75", True)

    def test_embed_respects_discord_limits(self):
        body = self.capture(self.overloaded_report())
        embed = body["embeds"][0]
        self.assertLessEqual(len(embed["title"]), 256)
        self.assertLessEqual(len(embed["fields"]), 25)
        for field in embed["fields"]:
            self.assertLessEqual(len(field["name"]), 256, field["name"])
            self.assertLessEqual(len(field["value"]), 1024, field["name"])

    def test_overflow_is_signposted_not_silently_dropped(self):
        values = "\n".join(f["value"] for f in
                           self.capture(self.overloaded_report())["embeds"][0]["fields"])
        self.assertIn("more", values)

    def test_mention_is_whitelisted_to_one_user(self):
        body = self.capture(self.overloaded_report())
        self.assertEqual(body["content"], "<@614843209872>")
        self.assertEqual(body["allowed_mentions"], {"users": ["614843209872"]})

    def test_celebrations_carry_no_mention(self):
        cold = TODAY - timedelta(days=60)
        status = build_status([ProblemRow("A", "Easy", cold, None, None)], TODAY, make_config())
        for report in (build_all_cold_report(status, "u", "Blind 75"),
                       build_complete_report(status, "u", "Blind 75")):
            body = self.capture(report, mention=True)
            self.assertNotIn("content", body, report.kind)

    def test_mention_disabled_in_config_wins(self):
        self.assertNotIn("content", self.capture(self.overloaded_report(), mention=False))


class TestState(unittest.TestCase):
    """The only thing stopping the twice-daily workflow repeating itself."""

    def setUp(self):
        import tempfile
        self.path = Path(tempfile.mkdtemp()) / "state.json"

    def test_daily_lock_round_trips(self):
        state = State(self.path)
        self.assertFalse(state.nagged_today(TODAY))
        state.mark_nagged(TODAY)
        state.save()
        self.assertTrue(State(self.path).nagged_today(TODAY))
        self.assertFalse(State(self.path).nagged_today(TODAY + timedelta(days=1)))

    def test_celebrations_persist_and_dedupe(self):
        state = State(self.path)
        state.mark_celebrated("blind75:all-cold")
        state.save()
        reloaded = State(self.path)
        self.assertTrue(reloaded.has_celebrated("blind75:all-cold"))
        self.assertFalse(reloaded.has_celebrated("blind75:complete"))
        reloaded.mark_celebrated("blind75:all-cold")
        self.assertEqual(reloaded.data["celebrated"], ["blind75:all-cold"])

    def test_missing_file_starts_empty(self):
        self.assertEqual(State(self.path).data, {})

    def test_corrupt_file_does_not_crash_the_run(self):
        self.path.write_text("{not json", encoding="utf-8")
        state = State(self.path)
        self.assertEqual(state.data, {})
        state.mark_nagged(TODAY)
        state.save()
        self.assertTrue(State(self.path).nagged_today(TODAY))

    def test_non_dict_json_is_ignored(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(State(self.path).data, {})

    def test_celebration_and_nag_locks_are_independent(self):
        state = State(self.path)
        state.mark_nagged(TODAY)
        state.mark_celebrated("blind75:50")
        state.save()
        reloaded = State(self.path)
        self.assertTrue(reloaded.nagged_today(TODAY))
        self.assertTrue(reloaded.has_celebrated("blind75:50"))


class TestServiceAccountValidation(unittest.TestCase):
    """A half-loaded credential must name its own cause.

    google-auth otherwise raises MalformedError listing missing fields, which
    says nothing about the real culprit: an unquoted multi-line value in .env,
    or the placeholder from .env.example left in place.
    """

    def setUp(self):
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def failure(self, raw: str) -> str:
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = raw
        with self.assertRaises(SystemExit) as ctx:
            sheets.build_client()
        return str(ctx.exception)

    def test_unparseable_json_mentions_quoting(self):
        message = self.failure("{")
        self.assertIn("not valid JSON", message)
        self.assertIn("single quotes", message)

    def test_env_example_placeholder_names_the_missing_fields(self):
        message = self.failure('{"type":"service_account","project_id":"..."}')
        for field in ("client_email", "token_uri", "private_key"):
            self.assertIn(field, message)

    def test_json_that_is_not_an_object(self):
        self.assertIn("isn't an object", self.failure('["a", "b"]'))

    def test_empty_private_key_is_caught(self):
        message = self.failure(
            '{"client_email":"a@b.com","token_uri":"https://x","private_key":""}')
        self.assertIn("private_key", message)


class TestSheetsApiErrors(unittest.TestCase):
    """403 is the commonest first-run failure and the fix is a Share dialog —
    which "The caller does not have permission" does not hint at."""

    KEY = '{"client_email": "nagger-bot@example.iam.gserviceaccount.com"}'

    def setUp(self):
        self._env = dict(os.environ)
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = self.KEY
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def failure(self, status: int, sheet_id: str = "1AbCdEf") -> str:
        from googleapiclient.errors import HttpError
        return sheets._api_failure(HttpError(mock.Mock(status=status), b"{}"), sheet_id)

    def test_403_names_the_address_to_share_with(self):
        message = self.failure(403)
        self.assertIn("nagger-bot@example.iam.gserviceaccount.com", message)
        self.assertIn("Share", message)

    def test_403_mentions_the_api_being_disabled_as_the_other_cause(self):
        self.assertIn("Sheets API is enabled", self.failure(403))

    def test_403_still_useful_when_the_key_is_unreadable(self):
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = "not json"
        self.assertIn("client_email", self.failure(403))

    def test_404_points_at_sheet_id(self):
        message = self.failure(404, "1AbCdEf")
        self.assertIn("1AbCdEf", message)
        self.assertIn("SHEET_ID", message)

    def test_other_statuses_are_not_swallowed(self):
        self.assertIn("500", self.failure(500))

    def test_service_account_email_survives_a_broken_key(self):
        for raw in ("", "not json", "[]", '{"type": "service_account"}'):
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = raw
            self.assertEqual(sheets.service_account_email(), "")


class TestConfigValidation(unittest.TestCase):
    def write(self, body: str) -> Path:
        import tempfile
        path = Path(tempfile.mkdtemp()) / "config.yml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_shipped_config_loads(self):
        cfg = load_config(Path(__file__).resolve().parent.parent / "config.yml")
        self.assertIn(cfg.list_key, ("blind75", "neetcode150", "neetcode250"))

    DISCORD = "channels:\n  discord:\n    enabled: true\n"

    def test_solve_days_as_a_list(self):
        cfg = load_config(self.write(
            "schedule:\n  solve_days: [mon, wed, sat]\n" + self.DISCORD))
        self.assertEqual(cfg.schedule.solve_days, frozenset({0, 2, 5}))

    def test_solve_days_as_a_preset(self):
        cfg = load_config(self.write(
            "schedule:\n  solve_days: weekdays\n" + self.DISCORD))
        self.assertEqual(cfg.schedule.solve_days, frozenset({0, 1, 2, 3, 4}))

    def test_unknown_preset_lists_the_alternatives(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write("schedule:\n  solve_days: sometimes\n"))
        self.assertIn("weekdays", str(ctx.exception))

    def test_unknown_day_name(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("schedule:\n  solve_days: [mon, funday]\n"))

    def test_review_days_default_to_the_non_solve_days(self):
        cfg = load_config(self.write(
            "schedule:\n  solve_days: weekdays\n" + self.DISCORD))
        self.assertEqual(cfg.schedule.review_days, frozenset({5, 6}))

    def test_review_days_can_be_narrowed(self):
        """The whole point: not every rest day has to be a review day."""
        cfg = load_config(self.write(
            "schedule:\n  solve_days: weekdays\n  review_days: [sun]\n" + self.DISCORD))
        self.assertEqual(cfg.schedule.review_days, frozenset({6}))
        self.assertFalse(cfg.schedule.is_review_day(date(2026, 8, 8)))   # Saturday
        self.assertTrue(cfg.schedule.is_review_day(date(2026, 8, 9)))    # Sunday

    def test_review_days_can_be_switched_off(self):
        cfg = load_config(self.write(
            "schedule:\n  solve_days: daily\n  review_days: []\n" + self.DISCORD))
        self.assertEqual(cfg.schedule.review_days, frozenset())

    def test_review_day_on_a_daily_cadence_is_now_possible(self):
        """Previously unreachable — `daily` left no rest days to hang it on."""
        cfg = load_config(self.write(
            "schedule:\n  solve_days: daily\n  review_days: [sun]\n" + self.DISCORD))
        self.assertTrue(cfg.schedule.is_solve_day(date(2026, 8, 9)))
        self.assertTrue(cfg.schedule.is_review_day(date(2026, 8, 9)))

    def test_both_empty_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write(
                "schedule:\n  solve_days: none\n  review_days: []\n" + self.DISCORD))
        self.assertIn("nothing would ever fire", str(ctx.exception))

    def test_bad_timezone(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("schedule:\n  timezone: Mars/Olympus\n"))

    def test_review_order(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("review:\n  first_days: 20\n  second_days: 10\n"))

    def test_all_channels_off(self):
        with self.assertRaises(ConfigError):
            load_config(self.write(
                "channels:\n  discord:\n    enabled: false\n"
                "  email:\n    enabled: false\n"
            ))

    def test_retired_sms_block_is_ignored_not_fatal(self):
        """A leftover `sms:` block from an older config must not hard-fail."""
        cfg = load_config(self.write(
            "channels:\n  discord:\n    enabled: true\n"
            "  sms:\n    enabled: true\n    carrier: verizon\n"
        ))
        self.assertTrue(cfg.channels.discord.enabled)
        self.assertFalse(hasattr(cfg.channels, "sms"))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(Path("does-not-exist.yml"))


if __name__ == "__main__":
    unittest.main()
