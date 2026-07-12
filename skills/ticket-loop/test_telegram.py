#!/usr/bin/env python3
"""Stdlib unittests for telegram.py's open-questions surface (no network).

Covers the pure accessors/formatters (_q_ticket, _format_age, render_questions,
questions_json, clear_questions) plus the `questions` subcommand end-to-end against
a scratch state.json under a temp TICKET_LOOP_STATE_DIR — asserting clear-by-id vs
clear-by-ticket, the no-match non-zero exit, and the invariant that a clear never
touches `offset` and never reaches the Telegram API.

Run: python3 skills/ticket-loop/test_telegram.py
"""

import argparse
import contextlib
import datetime
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("telegram_mod", HERE / "telegram.py")
telegram = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(telegram)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


class TestQTicket(unittest.TestCase):
    def test_rich_entry(self):
        v = {"ticket": "ABC-123", "text": "hi", "asked_at": "2026-07-11T10:00:00Z"}
        self.assertEqual(telegram._q_ticket(v), "ABC-123")

    def test_legacy_bare_string(self):
        self.assertEqual(telegram._q_ticket("ABC-123"), "ABC-123")


class TestFormatAge(unittest.TestCase):
    def test_days(self):
        self.assertEqual(telegram._format_age("2026-07-08T12:00:00Z", NOW), "3d ago")

    def test_hours(self):
        self.assertEqual(telegram._format_age("2026-07-11T07:00:00Z", NOW), "5h ago")

    def test_minutes(self):
        self.assertEqual(telegram._format_age("2026-07-11T11:58:00Z", NOW), "2m ago")

    def test_just_now(self):
        self.assertEqual(telegram._format_age("2026-07-11T11:59:30Z", NOW), "just now")

    def test_missing_is_dash(self):
        self.assertEqual(telegram._format_age(None, NOW), "—")
        self.assertEqual(telegram._format_age("not-a-date", NOW), "—")


class TestFirstLines(unittest.TestCase):
    def test_takes_first_two_nonempty(self):
        text = "line one\n\nline two\nline three"
        self.assertEqual(telegram._first_lines(text), ["line one", "line two"])

    def test_truncates_long(self):
        line = "x" * 100
        out = telegram._first_lines(line, width=10)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("…"))
        self.assertEqual(len(out[0]), 10)

    def test_empty(self):
        self.assertEqual(telegram._first_lines(""), [])
        self.assertEqual(telegram._first_lines(None), [])


class TestRenderQuestions(unittest.TestCase):
    def test_legacy_first_and_dash_text(self):
        questions = {
            "4567": {"ticket": "ABC-123", "text": "❓ ABC-123 — title\n1. why?",
                     "asked_at": "2026-07-08T12:00:00Z"},
            "9": "OLD-1",  # legacy bare string, no asked_at → sorts FIRST
        }
        out = telegram.render_questions(questions, NOW)
        lines = out.splitlines()
        # legacy sorts first
        self.assertEqual(lines[0], "OLD-1  msg 9  asked —")
        self.assertEqual(lines[1], "    —")  # missing text renders as —
        # rich entry follows, with age + first lines
        self.assertIn("ABC-123  msg 4567  asked 3d ago", out)
        self.assertIn("    ❓ ABC-123 — title", out)
        self.assertIn("    1. why?", out)

    def test_empty(self):
        self.assertEqual(telegram.render_questions({}, NOW), "no open questions")


class TestQuestionsJson(unittest.TestCase):
    def test_shape_and_legacy(self):
        questions = {
            "4567": {"ticket": "ABC-123", "text": "hi", "asked_at": "2026-07-11T10:00:00Z"},
            "9": "OLD-1",
        }
        out = telegram.questions_json(questions)
        by_id = {e["message_id"]: e for e in out}
        self.assertEqual(by_id["4567"]["ticket"], "ABC-123")
        self.assertEqual(by_id["4567"]["text"], "hi")
        self.assertEqual(by_id["9"], {"message_id": "9", "ticket": "OLD-1",
                                      "text": None, "asked_at": None})


class TestClearQuestions(unittest.TestCase):
    def sample(self):
        return {
            "100": {"ticket": "ABC-1", "text": "q1", "asked_at": "2026-07-10T12:00:00Z"},
            "101": {"ticket": "ABC-1", "text": "follow-up", "asked_at": "2026-07-11T09:00:00Z"},
            "200": {"ticket": "XYZ-9", "text": "q2", "asked_at": "2026-07-11T10:00:00Z"},
        }

    def test_clear_by_id_one_entry(self):
        q = self.sample()
        cleared = telegram.clear_questions(q, "100")
        self.assertEqual([mid for mid, _ in cleared], ["100"])
        self.assertNotIn("100", q)
        self.assertIn("101", q)  # sibling ABC-1 entry untouched
        self.assertIn("200", q)

    def test_clear_by_ticket_all_entries(self):
        q = self.sample()
        cleared = telegram.clear_questions(q, "abc-1")  # case-insensitive
        self.assertEqual(sorted(mid for mid, _ in cleared), ["100", "101"])
        self.assertNotIn("100", q)
        self.assertNotIn("101", q)
        self.assertIn("200", q)

    def test_no_match(self):
        q = self.sample()
        cleared = telegram.clear_questions(q, "NOPE-9")
        self.assertEqual(cleared, [])
        self.assertEqual(len(q), 3)


class TestCmdQuestions(unittest.TestCase):
    """`questions` subcommand against a scratch state.json (no network)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.json"
        self._orig_state_path = telegram.STATE_PATH
        telegram.STATE_PATH = self.state_path
        # Any Telegram API call is a test failure — clear must never reach the network.
        self._orig_api = telegram.api
        self._orig_request = telegram._request
        telegram.api = self._boom
        telegram._request = self._boom
        self.write_state({
            "offset": 42,
            "questions": {
                "100": {"ticket": "ABC-1", "text": "q1", "asked_at": "2026-07-10T12:00:00Z"},
                "101": {"ticket": "ABC-1", "text": "follow-up", "asked_at": "2026-07-11T09:00:00Z"},
                "200": {"ticket": "XYZ-9", "text": "q2", "asked_at": "2026-07-11T10:00:00Z"},
                "9": "OLD-1",
            },
        })

    def tearDown(self):
        telegram.STATE_PATH = self._orig_state_path
        telegram.api = self._orig_api
        telegram._request = self._orig_request
        self._tmp.cleanup()

    def _boom(self, *a, **k):
        raise AssertionError("Telegram API must not be called by `questions`")

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def read_state(self):
        return json.loads(self.state_path.read_text())

    def run_questions(self, clear=None, want_json=False):
        args = argparse.Namespace(clear=clear, json=want_json)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            telegram.cmd_questions(args)
        return buf.getvalue()

    def test_list(self):
        out = self.run_questions()
        self.assertIn("ABC-1  msg 100", out)
        self.assertIn("OLD-1  msg 9  asked —", out)

    def test_json(self):
        out = self.run_questions(want_json=True)
        data = json.loads(out)
        self.assertEqual({e["message_id"] for e in data}, {"100", "101", "200", "9"})

    def test_clear_by_id_leaves_offset(self):
        self.run_questions(clear="100")
        st = self.read_state()
        self.assertEqual(st["offset"], 42)  # invariant: offset untouched
        self.assertNotIn("100", st["questions"])
        self.assertIn("101", st["questions"])

    def test_clear_by_ticket_all(self):
        self.run_questions(clear="ABC-1")
        st = self.read_state()
        self.assertEqual(st["offset"], 42)
        self.assertNotIn("100", st["questions"])
        self.assertNotIn("101", st["questions"])
        self.assertIn("200", st["questions"])

    def test_no_match_nonzero_and_no_write(self):
        before = self.read_state()
        with self.assertRaises(SystemExit) as ctx:
            self.run_questions(clear="NOPE-1")
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.read_state(), before)  # no write on no-match


class TestCmdPeek(unittest.TestCase):
    """`peek` must count pending human messages WITHOUT consuming the offset —
    save_state is monkeypatched to a hard failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.json"
        self._orig_state_path = telegram.STATE_PATH
        telegram.STATE_PATH = self.state_path
        self.state_path.write_text(json.dumps({"offset": 100, "questions": {}}))
        self._orig_api = telegram.api
        self._orig_save = telegram.save_state
        telegram.save_state = self._no_save
        os.environ["AGENT_TELEGRAM_CHAT_ID"] = "-100777"
        self.api_params = None

    def tearDown(self):
        telegram.STATE_PATH = self._orig_state_path
        telegram.api = self._orig_api
        telegram.save_state = self._orig_save
        os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
        self._tmp.cleanup()

    def _no_save(self, *a, **k):
        raise AssertionError("peek must never write state (offset consumed!)")

    def fake_api(self, updates):
        def _api(method, params, **kw):
            self.assertEqual(method, "getUpdates")
            self.api_params = params
            return updates
        telegram.api = _api

    def run_peek(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            telegram.cmd_peek(argparse.Namespace())
        return buf.getvalue().strip()

    def msg(self, chat="-100777", bot=False):
        return {"update_id": 101, "message": {
            "message_id": 5, "chat": {"id": int(chat)},
            "from": {"is_bot": bot, "username": "u"}, "text": "hi"}}

    def test_counts_human_messages_at_stored_offset(self):
        self.fake_api([self.msg(), self.msg()])
        self.assertEqual(self.run_peek(), "2")
        self.assertEqual(self.api_params["offset"], 100)  # peeks AT the offset
        self.assertEqual(self.api_params["timeout"], 0)
        # state untouched on disk
        self.assertEqual(json.loads(self.state_path.read_text())["offset"], 100)

    def test_ignores_bots_and_other_chats(self):
        self.fake_api([self.msg(bot=True), self.msg(chat="-42"), self.msg()])
        self.assertEqual(self.run_peek(), "1")

    def test_empty(self):
        self.fake_api([])
        self.assertEqual(self.run_peek(), "0")


if __name__ == "__main__":
    unittest.main()
