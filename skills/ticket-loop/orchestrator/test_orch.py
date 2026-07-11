#!/usr/bin/env python3
"""Stdlib unittests for orch.py — the orchestrator's scheduling brain (no network,
no docker). Import idiom mirrors test_telegram.py.

Run: python3 skills/ticket-loop/orchestrator/test_orch.py
(PyYAML must be importable — it is in the container image and on any machine that
can already run dev-workflow/test_validate.py.)
"""

import datetime
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("orch_mod", HERE / "orch.py")
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def make_roster_dir(tmp, projects_yaml=None, top_yaml=""):
    """Write a roster + valid work trees under tmp; returns the roster path.
    Default: one project `alpha` with the marker file present."""
    root = Path(tmp)
    wt = root / "alpha"
    wt.mkdir(exist_ok=True)
    (wt / ".dw-agent-clone").touch()
    (root / "alpha.env").touch()
    if projects_yaml is None:
        projects_yaml = f"""
projects:
  - name: alpha
    work_tree: {wt}
    env_file: {root}/alpha.env
    state_dir: {root}/state-alpha
"""
    roster = root / "roster.yml"
    roster.write_text(f"root: {root}\n{top_yaml}\n{projects_yaml}")
    return roster


class TestParseDuration(unittest.TestCase):
    def test_units(self):
        self.assertEqual(orch.parse_duration("10m"), 600)
        self.assertEqual(orch.parse_duration("90m"), 5400)
        self.assertEqual(orch.parse_duration("8h"), 28800)
        self.assertEqual(orch.parse_duration("45s"), 45)
        self.assertEqual(orch.parse_duration("1d"), 86400)

    def test_bare_int_is_seconds(self):
        self.assertEqual(orch.parse_duration(300), 300)
        self.assertEqual(orch.parse_duration("300"), 300)

    def test_junk_raises(self):
        with self.assertRaises(orch.RosterError):
            orch.parse_duration("soon")
        with self.assertRaises(orch.RosterError):
            orch.parse_duration("10 minutes")


class TestLoadRoster(unittest.TestCase):
    def test_defaults_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = orch.load_roster(make_roster_dir(tmp))
        self.assertEqual(roster["cfg"]["ladder_s"], [600, 1200, 2400, 3600])
        self.assertEqual(roster["cfg"]["waiting_interval_s"], 1200)
        self.assertEqual(roster["cfg"]["force_full_every_s"], 28800)
        self.assertEqual(roster["cfg"]["pass_timeout_s"], 5400)
        self.assertEqual(roster["cfg"]["mem_floor_mb"], 2560)
        self.assertEqual(roster["cfg"]["error_escalate_after"], 3)
        self.assertEqual(roster["cfg"]["crash_park_after"], 3)
        p = roster["projects"][0]
        self.assertEqual(p["name"], "alpha")
        self.assertEqual(p["cadence"], "adaptive")
        self.assertIsNone(p["model"])
        self.assertIsNone(p["window"])

    def test_per_project_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wt = root / "alpha"; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            (root / "alpha.env").touch()
            roster_path = root / "roster.yml"
            roster_path.write_text(f"""
root: {root}
cadence: adaptive
projects:
  - name: alpha
    work_tree: {wt}
    env_file: {root}/alpha.env
    state_dir: {root}/state-alpha
    cadence: fixed
    interval: 45m
    model: sonnet
    tz: Asia/Kolkata
    window: "09:00-20:00"
""")
            roster = orch.load_roster(roster_path)
        p = roster["projects"][0]
        self.assertEqual(p["cadence"], "fixed")
        self.assertEqual(p["interval_s"], 2700)
        self.assertEqual(p["model"], "sonnet")
        self.assertEqual(p["tz"], "Asia/Kolkata")
        self.assertEqual(p["window"], "09:00-20:00")

    def test_missing_required_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = "projects:\n  - name: alpha\n    work_tree: /x\n"
            with self.assertRaises(orch.RosterError):
                orch.load_roster(make_roster_dir(tmp, projects_yaml=bad))

    def test_empty_or_duplicate_projects_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(orch.RosterError):
                orch.load_roster(make_roster_dir(tmp, projects_yaml="projects: []\n"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wt = root / "alpha"; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            dup = f"""
projects:
  - {{name: alpha, work_tree: {wt}, env_file: {root}/e, state_dir: {root}/s}}
  - {{name: alpha, work_tree: {wt}, env_file: {root}/e, state_dir: {root}/s2}}
"""
            with self.assertRaises(orch.RosterError):
                orch.load_roster(make_roster_dir(tmp, projects_yaml=dup))

    def test_bad_cadence_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wt = root / "alpha"; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            bad = f"""
projects:
  - {{name: alpha, work_tree: {wt}, env_file: {root}/e, state_dir: {root}/s, cadence: sometimes}}
"""
            with self.assertRaises(orch.RosterError):
                orch.load_roster(make_roster_dir(tmp, projects_yaml=bad))


class TestWorkTreeGuard(unittest.TestCase):
    """Spec §8: positive allowlist — under root AND carrying .dw-agent-clone."""

    def test_valid_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "proj"; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            orch.check_work_tree({"name": "p", "work_tree": str(wt)}, tmp)  # no raise

    def test_missing_marker_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "prod-checkout"; wt.mkdir()   # a live checkout: NO marker
            with self.assertRaises(orch.RosterError):
                orch.check_work_tree({"name": "p", "work_tree": str(wt)}, tmp)

    def test_outside_root_refused_even_with_marker(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            wt = Path(other) / "proj"; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            with self.assertRaises(orch.RosterError):
                orch.check_work_tree({"name": "p", "work_tree": str(wt)}, tmp)

    def test_root_itself_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".dw-agent-clone").touch()
            with self.assertRaises(orch.RosterError):
                orch.check_work_tree({"name": "p", "work_tree": tmp}, tmp)


class TestStateIO(unittest.TestCase):
    def test_roundtrip_and_ensure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orch-state.json"
            st = orch.load_state(path)
            self.assertEqual(st, {})
            orch.ensure_projects(st, [{"name": "a"}, {"name": "b"}])
            self.assertIn("a", st["projects"])
            self.assertEqual(st["projects"]["a"]["dry_streak"], 0)
            self.assertEqual(st["rr_next"], 0)
            orch.save_state(path, st)
            st2 = orch.load_state(path)
            self.assertEqual(st, st2)

    def test_ensure_drops_removed_projects(self):
        st = {"projects": {"gone": orch.default_pstate()}, "rr_next": 5}
        orch.ensure_projects(st, [{"name": "kept"}])
        self.assertEqual(set(st["projects"]), {"kept"})

    def test_corrupt_state_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orch-state.json"
            path.write_text("{not json")
            st = orch.load_state(path)
            self.assertEqual(st, {})
            self.assertTrue(path.with_suffix(".json.corrupt").exists())


class TestMemAvailable(unittest.TestCase):
    def test_parses_meminfo(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "meminfo"
            f.write_text("MemTotal:  8000000 kB\nMemAvailable:  3072000 kB\n")
            self.assertEqual(orch.mem_available_mb(str(f)), 3000)

    def test_missing_file_is_none(self):
        self.assertIsNone(orch.mem_available_mb("/nonexistent/meminfo"))


if __name__ == "__main__":
    unittest.main()
