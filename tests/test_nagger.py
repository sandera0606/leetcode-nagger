"""Offline tests — no Google, no Discord, no SMTP.

    python -m unittest discover tests
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nagger.config import Channels, Config, DiscordConfig, EmailConfig, Review, Schedule, SmsConfig
from nagger.config import ConfigError, load_config
from nagger.messages import build_complete_report, build_milestone_report, build_report, plain
from nagger import notify
from nagger.notify import discord, mail
from nagger.notify.sms import normalize_number
from nagger.tracker import ProblemRow, build_status, compute_streak, find_header, parse_date, parse_rows

TODAY = date(2026, 8, 7)  # a Friday


def make_config(**overrides) -> Config:
    schedule = Schedule(
        cadence=overrides.pop("cadence", "weekdays"),
        solve_days=frozenset(overrides.pop("solve_days", {0, 1, 2, 3, 4})),
        problems_per_day=overrides.pop("problems_per_day", 1),
        timezone="America/New_York",
        nag_hour=19,
        rest_day_review=overrides.pop("rest_day_review", True),
    )
    review = Review(
        enabled=overrides.pop("review_enabled", True),
        first_days=overrides.pop("first_days", 7),
        second_days=overrides.pop("second_days", 21),
    )
    channels = Channels(
        discord=DiscordConfig(enabled=True, mention=True),
        email=EmailConfig(enabled=False, subject_prefix="[LeetCode]"),
        sms=SmsConfig(enabled=False, provider="carrier_gateway", carrier="verizon"),
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
        cfg = make_config(cadence="no_sundays", solve_days={0, 1, 2, 3, 4, 5})
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

    def test_nag_has_sections_and_sms_fits(self):
        report = build_report(self.status(), "https://example.com", "Blind 75", mention=True)
        self.assertTrue(report.sections)
        self.assertLessEqual(len(report.sms), 300)
        self.assertIn("LeetCode", report.sms)
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
                       build_complete_report(status, "u", "Blind 75")):
            self.assertFalse(report.mention)
            self.assertLessEqual(len(report.sms), 300)


class TestSms(unittest.TestCase):
    def test_number_normalisation(self):
        for raw in ("+1 (555) 123-4567", "15551234567", "555-123-4567"):
            self.assertEqual(normalize_number(raw), "5551234567")


class TestDispatch(unittest.TestCase):
    """One misconfigured channel must never take the others down."""

    def setUp(self):
        self._env = dict(os.environ)
        for key in ("EMAIL_TO", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                    "DISCORD_WEBHOOK_URL", "SMS_TO"):
            os.environ.pop(key, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        rows = [ProblemRow("Two Sum", "Easy", None, None, None)]
        self.report = build_report(
            build_status(rows, TODAY, make_config()), "u", "Blind 75", True)

    def channels(self, **kw):
        return Channels(
            discord=DiscordConfig(enabled=kw.get("discord", True), mention=True),
            email=EmailConfig(enabled=kw.get("email", False), subject_prefix="[LC]"),
            sms=SmsConfig(enabled=kw.get("sms", False),
                          provider="carrier_gateway", carrier="verizon"),
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


class TestConfigValidation(unittest.TestCase):
    def write(self, body: str) -> Path:
        import tempfile
        path = Path(tempfile.mkdtemp()) / "config.yml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_shipped_config_loads(self):
        cfg = load_config(Path(__file__).resolve().parent.parent / "config.yml")
        self.assertIn(cfg.list_key, ("blind75", "neetcode150", "neetcode250"))

    def test_bad_cadence(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("schedule:\n  cadence: sometimes\n"))

    def test_custom_cadence_needs_days(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("schedule:\n  cadence: custom\n"))

    def test_custom_cadence_days(self):
        cfg = load_config(self.write(
            "schedule:\n  cadence: custom\n  days: [mon, wed, sat]\n"
            "channels:\n  discord:\n    enabled: true\n"
        ))
        self.assertEqual(cfg.schedule.solve_days, frozenset({0, 2, 5}))

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
                "  email:\n    enabled: false\n  sms:\n    enabled: false\n"
            ))

    def test_unknown_carrier(self):
        with self.assertRaises(ConfigError):
            load_config(self.write(
                "channels:\n  sms:\n    enabled: true\n    carrier: pigeon\n"
            ))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(Path("does-not-exist.yml"))


if __name__ == "__main__":
    unittest.main()
