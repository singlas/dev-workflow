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


class TestFindRepoRoot(unittest.TestCase):
    """cwd (the repo you're operating on) must win over the script's own tree —
    the bridge lives inside the dev-workflow checkout (which has .git), so a
    script-first walk would resolve dev-workflow and read ITS .env instead of the
    target repo's. Regression guard for the pubx-hil/.env bridge bug."""

    def test_cwd_wins_over_script_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp).resolve() / "target-repo"
            (work / ".git").mkdir(parents=True)   # a git work tree
            cwd0 = os.getcwd()
            try:
                os.chdir(work)
                # __file__ lives inside the dev-workflow checkout (its own .git),
                # yet cwd-first must return the work tree we're standing in.
                self.assertEqual(telegram.find_repo_root(), work)
            finally:
                os.chdir(cwd0)

    def test_target_env_wins_not_framework_env(self):
        # The concrete bug: creds in the target repo's .env must load, and the
        # framework checkout's absent .env must NOT shadow them.
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp).resolve() / "pubx-hil"
            (work / ".git").mkdir(parents=True)
            (work / ".env").write_text("AGENT_TELEGRAM_CHAT_ID=-100999\n")
            cwd0 = os.getcwd()
            saved_root, saved_chat = telegram.REPO_ROOT, os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
            try:
                os.chdir(work)
                telegram.REPO_ROOT = telegram.find_repo_root()   # recompute for the new cwd
                telegram.load_env()
                self.assertEqual(os.environ.get("AGENT_TELEGRAM_CHAT_ID"), "-100999")
            finally:
                os.chdir(cwd0)
                telegram.REPO_ROOT = saved_root
                os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
                if saved_chat is not None:
                    os.environ["AGENT_TELEGRAM_CHAT_ID"] = saved_chat


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
                                      "project": None, "context": None,
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

    def msg(self, chat="-100777", bot=False, uid=101):
        return {"update_id": uid, "message": {
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

    def test_shared_mode_no_offset_param_floor_filters(self):
        """Shared bot: getUpdates must NOT carry an offset (an offset acks
        bot-wide, destroying sibling projects' messages); the stored offset acts
        as a local floor instead."""
        os.environ["TELEGRAM_SHARED_BOT"] = "1"
        try:
            self.fake_api([self.msg(uid=99), self.msg(uid=150)])  # floor is 100
            self.assertEqual(self.run_peek(), "1")
            self.assertNotIn("offset", self.api_params)
        finally:
            os.environ.pop("TELEGRAM_SHARED_BOT", None)


class TestCmdPollShared(unittest.TestCase):
    """Shared-bot (no-ack) poll: no offset param to getUpdates, updates below the
    local floor are skipped, foreign-chat updates advance the floor but emit
    nothing, and an all-foreign batch sleeps out the long-poll window instead of
    letting the caller spin."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.json"
        self._orig_state_path = telegram.STATE_PATH
        telegram.STATE_PATH = self.state_path
        self.state_path.write_text(json.dumps({"offset": 100, "questions": {}}))
        self._orig_api = telegram.api
        os.environ["AGENT_TELEGRAM_CHAT_ID"] = "-100777"
        os.environ["TELEGRAM_SHARED_BOT"] = "1"
        self.api_params = None
        self._orig_sleep = telegram.time.sleep
        self.slept = []
        telegram.time.sleep = self.slept.append

    def tearDown(self):
        telegram.STATE_PATH = self._orig_state_path
        telegram.api = self._orig_api
        telegram.time.sleep = self._orig_sleep
        os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_SHARED_BOT", None)
        self._tmp.cleanup()

    def fake_api(self, updates):
        def _api(method, params, **kw):
            self.assertEqual(method, "getUpdates")
            self.api_params = params
            return updates
        telegram.api = _api

    def upd(self, uid, chat="-100777", text="hi"):
        return {"update_id": uid, "message": {
            "message_id": uid, "chat": {"id": int(chat)},
            "from": {"is_bot": False, "username": "u", "id": 7}, "text": text}}

    def run_poll(self, timeout=25):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            telegram.cmd_poll(argparse.Namespace(timeout=timeout))
        return [json.loads(line) for line in buf.getvalue().splitlines()]

    def read_offset(self):
        return json.loads(self.state_path.read_text())["offset"]

    def test_no_offset_floor_skip_and_local_advance(self):
        self.fake_api([self.upd(99), self.upd(150, chat="-42"), self.upd(151)])
        out = self.run_poll()
        self.assertNotIn("offset", self.api_params)
        self.assertEqual([m["message_id"] for m in out], [151])  # 99 < floor, -42 foreign
        self.assertEqual(self.read_offset(), 152)               # local floor only
        self.assertEqual(self.slept, [])                        # emitted → no pacing sleep

    def test_all_foreign_batch_paces_instead_of_spinning(self):
        self.fake_api([self.upd(150, chat="-42")])
        out = self.run_poll(timeout=25)
        self.assertEqual(out, [])
        self.assertEqual(len(self.slept), 1)
        self.assertGreater(self.slept[0], 0)
        self.assertEqual(self.read_offset(), 151)  # scanned foreign ids don't re-scan

    def test_unshared_poll_still_acks_via_offset(self):
        os.environ.pop("TELEGRAM_SHARED_BOT", None)
        self.fake_api([self.upd(150)])
        out = self.run_poll()
        self.assertEqual(self.api_params["offset"], 100)
        self.assertEqual([m["message_id"] for m in out], [150])
        self.assertEqual(self.read_offset(), 151)


class TestQEntryProjectContext(unittest.TestCase):
    def test_entry_with_project_and_context(self):
        e = telegram._q_entry("pay-5", "q", project="pt-api", context="bug: x")
        self.assertEqual(e["ticket"], "PAY-5")
        self.assertEqual(e["project"], "pt-api")
        self.assertEqual(e["context"], "bug: x")

    def test_entry_ticketless_for_disambiguation(self):
        e = telegram._q_entry(None, "which project?", context="bug: checkout")
        self.assertIsNone(e["ticket"])
        self.assertEqual(e["context"], "bug: checkout")
        self.assertNotIn("project", e)          # omitted when not given

    def test_accessors(self):
        e = {"ticket": "PAY-5", "project": "pt-api", "context": "c"}
        self.assertEqual(telegram._q_project(e), "pt-api")
        self.assertEqual(telegram._q_context(e), "c")
        self.assertIsNone(telegram._q_project("PAY-5"))   # legacy bare string
        self.assertIsNone(telegram._q_context({"ticket": "X"}))


class TestSendRecordsRouting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.json"
        self._orig_state_path = telegram.STATE_PATH
        telegram.STATE_PATH = self.state_path
        self._orig_api = telegram.api
        telegram.api = lambda method, params, **kw: {"message_id": 900}
        os.environ["AGENT_TELEGRAM_CHAT_ID"] = "-100777"

    def tearDown(self):
        telegram.STATE_PATH = self._orig_state_path
        telegram.api = self._orig_api
        os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
        self._tmp.cleanup()

    def send(self, text="q", ticket=None, project=None, context=None):
        with contextlib.redirect_stdout(io.StringIO()):
            telegram.cmd_send(argparse.Namespace(text=[text], ticket=ticket,
                                                 project=project, context=context))
        return (json.loads(self.state_path.read_text())["questions"]
                if self.state_path.exists() else {})

    def test_ticket_with_project_recorded(self):
        q = self.send(ticket="PAY-5", project="pt-api")
        self.assertEqual(q["900"]["ticket"], "PAY-5")
        self.assertEqual(q["900"]["project"], "pt-api")

    def test_context_only_recorded_without_ticket(self):
        q = self.send(text="which project?", context="bug: checkout fails")
        self.assertIsNone(q["900"]["ticket"])
        self.assertEqual(q["900"]["context"], "bug: checkout fails")

    def test_plain_send_records_nothing(self):
        self.assertEqual(self.send(text="just an update"), {})


class TestPollEmitsRouting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.json"
        self._orig_state_path = telegram.STATE_PATH
        telegram.STATE_PATH = self.state_path
        self._orig_api = telegram.api
        os.environ["AGENT_TELEGRAM_CHAT_ID"] = "-100777"
        os.environ.pop("TELEGRAM_SHARED_BOT", None)

    def tearDown(self):
        telegram.STATE_PATH = self._orig_state_path
        telegram.api = self._orig_api
        os.environ.pop("AGENT_TELEGRAM_CHAT_ID", None)
        self._tmp.cleanup()

    def write(self, questions):
        self.state_path.write_text(json.dumps({"offset": 0, "questions": questions}))

    def reply(self, uid, to_mid, text="ok"):
        telegram.api = lambda method, params, **kw: [{"update_id": uid, "message": {
            "message_id": uid, "chat": {"id": -100777},
            "from": {"is_bot": False, "username": "u", "id": 7}, "text": text,
            "reply_to_message": {"message_id": to_mid}}}]

    def run_poll(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            telegram.cmd_poll(argparse.Namespace(timeout=0))
        return [json.loads(l) for l in buf.getvalue().splitlines() if l]

    def test_reply_carries_recorded_project(self):
        self.write({"500": {"ticket": "PAY-5", "project": "pt-api",
                            "text": "q", "asked_at": None}})
        self.reply(600, 500)
        out = self.run_poll()
        self.assertEqual(out[0]["ticket"], "PAY-5")
        self.assertEqual(out[0]["project"], "pt-api")   # routes without a tracker read
        self.assertIsNone(out[0]["context"])

    def test_pre_ticket_context_reply_has_no_ticket(self):
        self.write({"500": {"ticket": None, "context": "bug: checkout fails",
                            "text": "which project?", "asked_at": None}})
        self.reply(600, 500, "pt-api")
        out = self.run_poll()
        self.assertIsNone(out[0]["ticket"])
        self.assertEqual(out[0]["context"], "bug: checkout fails")
        self.assertEqual(out[0]["text"], "pt-api")       # the human's answer

    def test_questions_json_exposes_project_context(self):
        data = telegram.questions_json({"500": {"ticket": "PAY-5", "project": "pt-api",
                                                "context": "c", "text": "q", "asked_at": None}})
        self.assertEqual(data[0]["project"], "pt-api")
        self.assertEqual(data[0]["context"], "c")


if __name__ == "__main__":
    unittest.main()
