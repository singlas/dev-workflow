#!/usr/bin/env python3
"""Stdlib unittests for telegram-wake.py — the pure parts only (no network:
the long-poll loop is exercised in production, its decisions are tested here).

Run: python3 skills/ticket-loop/orchestrator/test_wake.py
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wake_mod", HERE / "telegram-wake.py")
wake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wake)


class ReadBotToken(unittest.TestCase):
    def test_reads_plain_and_quoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.env"
            f.write_text("GH_TOKEN=x\nTELEGRAM_BOT_TOKEN=123:abc\n")
            self.assertEqual(wake.read_bot_token(f), "123:abc")
            f.write_text('TELEGRAM_BOT_TOKEN="456:def"\n')
            self.assertEqual(wake.read_bot_token(f), "456:def")

    def test_missing_file_or_key_is_none(self):
        self.assertIsNone(wake.read_bot_token("/nonexistent/x.env"))
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.env"
            f.write_text("GH_TOKEN=x\n")
            self.assertIsNone(wake.read_bot_token(f))

    def test_commented_line_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.env"
            f.write_text("# TELEGRAM_BOT_TOKEN=dead\nTELEGRAM_BOT_TOKEN=live:1\n")
            self.assertEqual(wake.read_bot_token(f), "live:1")


class ReadOffset(unittest.TestCase):
    def test_reads_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"offset": 42}))
            self.assertEqual(wake.read_offset(tmp), 42)

    def test_missing_or_bad_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(wake.read_offset(tmp), 0)
            (Path(tmp) / "state.json").write_text("not json")
            self.assertEqual(wake.read_offset(tmp), 0)
            (Path(tmp) / "state.json").write_text(json.dumps({"offset": None}))
            self.assertEqual(wake.read_offset(tmp), 0)


class Wakeworthy(unittest.TestCase):
    def test_message_updates_wake(self):
        ups = [{"update_id": 5, "message": {"text": "question: hi"}},
               {"update_id": 7, "message": {"text": "more"}}]
        self.assertEqual(wake.wakeworthy(ups), 7)

    def test_noise_does_not_wake(self):
        ups = [{"update_id": 5, "my_chat_member": {}},
               {"update_id": 6, "edited_message": {"text": "x"}}]
        self.assertIsNone(wake.wakeworthy(ups))

    def test_channel_post_wakes_and_empty_is_none(self):
        self.assertEqual(wake.wakeworthy([{"update_id": 3, "channel_post": {}}]), 3)
        self.assertIsNone(wake.wakeworthy([]))


class SignalRunNow(unittest.TestCase):
    def test_writes_name_once_never_clobbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "run-now"
            self.assertTrue(wake.signal_run_now(f, "alpha"))
            self.assertEqual(f.read_text().strip(), "alpha")
            # a pending signal (another tenant's wake) is never overwritten
            self.assertFalse(wake.signal_run_now(f, "beta"))
            self.assertEqual(f.read_text().strip(), "alpha")


class LoadProjects(unittest.TestCase):
    def _roster(self, tmp, entries):
        r = Path(tmp) / "roster.yml"
        r.write_text("projects:\n" + "".join(entries))
        return r

    def _env(self, tmp, name, token):
        f = Path(tmp) / f"{name}.env"
        f.write_text(f"TELEGRAM_BOT_TOKEN={token}\n" if token else "GH_TOKEN=x\n")
        return f

    def test_enabled_with_token_watched_disabled_and_tokenless_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self._env(tmp, "a", "111:a")
            b = self._env(tmp, "b", None)
            c = self._env(tmp, "c", "333:c")
            roster = self._roster(tmp, [
                f"  - {{name: a, env_file: {a}, state_dir: {tmp}/sa}}\n",
                f"  - {{name: b, env_file: {b}, state_dir: {tmp}/sb}}\n",
                f"  - {{name: c, env_file: {c}, state_dir: {tmp}/sc, enabled: false}}\n",
            ])
            projs = wake.load_projects(roster)
        self.assertEqual([p["name"] for p in projs], ["a"])
        self.assertEqual(projs[0]["token"], "111:a")

    def test_shared_token_deduped_first_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self._env(tmp, "a", "999:shared")
            b = self._env(tmp, "b", "999:shared")
            roster = self._roster(tmp, [
                f"  - {{name: a, env_file: {a}, state_dir: {tmp}/sa}}\n",
                f"  - {{name: b, env_file: {b}, state_dir: {tmp}/sb}}\n",
            ])
            projs = wake.load_projects(roster)
        self.assertEqual([p["name"] for p in projs], ["a"])


if __name__ == "__main__":
    unittest.main()
