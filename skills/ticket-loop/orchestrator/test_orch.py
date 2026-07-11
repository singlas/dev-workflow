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


class TestWindows(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(orch.parse_window("09:00-20:00"), (540, 1200))
        with self.assertRaises(orch.RosterError):
            orch.parse_window("9am-8pm")
        with self.assertRaises(orch.RosterError):
            orch.parse_window("25:00-26:00")

    def test_in_window_plain_and_wrap(self):
        w = (540, 1200)                       # 09:00-20:00
        self.assertTrue(orch.minute_in_window(540, w))    # inclusive start
        self.assertTrue(orch.minute_in_window(1199, w))
        self.assertFalse(orch.minute_in_window(1200, w))  # exclusive end
        self.assertFalse(orch.minute_in_window(300, w))
        night = (1320, 360)                   # 22:00-06:00 overnight
        self.assertTrue(orch.minute_in_window(1380, night))
        self.assertTrue(orch.minute_in_window(120, night))
        self.assertFalse(orch.minute_in_window(720, night))
        self.assertTrue(orch.minute_in_window(0, (0, 0)))  # equal ends = always open

    def test_seconds_until_open_intersection(self):
        # NOW is 12:00 UTC. Intersection of 09:00-20:00 and 13:00-18:00 opens at 13:00.
        wins = [(540, 1200), (780, 1080)]
        self.assertEqual(orch.seconds_until_open(wins, "UTC", NOW), 3600)
        # Inside both → 0.
        self.assertEqual(orch.seconds_until_open([(540, 1200)], "UTC", NOW), 0)
        # Empty intersection → None.
        self.assertIsNone(orch.seconds_until_open([(0, 60), (120, 180)], "UTC", NOW))

    def test_repo_schedule_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "dev-workflow.yml").write_text(
                "schedule:\n  window: \"09:00-20:00\"\n  tz: UTC\n")
            sched = orch.read_repo_schedule(tmp)
            self.assertEqual(sched["window"], "09:00-20:00")
            self.assertEqual(sched["tz"], "UTC")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(orch.read_repo_schedule(tmp), {})


class TestPickNext(unittest.TestCase):
    def roster2(self, tmp, window_b=None):
        """Two adaptive projects a, b (b optionally windowed)."""
        root = Path(tmp)
        entries = []
        for name in ("a", "b"):
            wt = root / name; wt.mkdir(); (wt / ".dw-agent-clone").touch()
            e = {"name": name, "work_tree": str(wt), "env_file": str(root / f"{name}.env"),
                 "state_dir": str(root / f"state-{name}"), "model": None, "tz": "UTC",
                 "window": window_b if name == "b" else None,
                 "cadence": "adaptive", "interval_s": 1800}
            entries.append(e)
        cfg = {k: v for k, v in orch.DEFAULTS.items()}
        cfg["ladder_s"] = [600, 1200, 2400, 3600]
        for k in ("interval", "waiting_interval", "force_full_every",
                  "pass_timeout", "requeue_delay", "crash_park_for"):
            cfg[k + "_s"] = orch.parse_duration(cfg[k])
        for k in ("mem_floor_mb", "error_escalate_after", "crash_park_after"):
            cfg[k] = int(cfg[k])
        return {"root": str(root), "cfg": cfg, "projects": entries}

    def fresh_state(self, roster):
        st = {}
        orch.ensure_projects(st, roster["projects"])
        return st

    def test_round_robin_order_and_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["action"], "run")
            self.assertEqual(d["project"]["name"], "a")
            st["rr_next"] = 1          # record() advances this; simulate
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["project"]["name"], "b")

    def test_first_ever_run_is_forced_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            d = orch.pick_next(roster, st, NOW)
            self.assertTrue(d["force_full"])
            self.assertFalse(d["precheck"])   # forced-full pass skips the pre-check

    def test_recent_full_pass_enables_precheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            st["projects"]["a"]["last_full_pass"] = orch.to_iso(
                NOW - datetime.timedelta(hours=1))
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["project"]["name"], "a")
            self.assertFalse(d["force_full"])
            self.assertTrue(d["precheck"])

    def test_stale_full_pass_forces_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            st["projects"]["a"]["last_full_pass"] = orch.to_iso(
                NOW - datetime.timedelta(hours=9))   # > 8h default
            d = orch.pick_next(roster, st, NOW)
            self.assertTrue(d["force_full"])

    def test_fixed_cadence_never_prechecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            roster["projects"][0]["cadence"] = "fixed"
            st = self.fresh_state(roster)
            st["projects"]["a"]["last_full_pass"] = orch.to_iso(NOW)
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["project"]["name"], "a")
            self.assertFalse(d["precheck"])

    def test_ineligible_projects_produce_sleep(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            for name in ("a", "b"):
                st["projects"][name]["next_eligible"] = orch.to_iso(
                    NOW + datetime.timedelta(minutes=7))
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["action"], "sleep")
            self.assertEqual(d["sleep_seconds"], 420)   # sleep to min(next_eligible)

    def test_window_skip_does_not_touch_ladder(self):
        # b is windowed out (window opens at 13:00, NOW=12:00); a is not yet eligible.
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp, window_b="13:00-18:00")
            st = self.fresh_state(roster)
            st["rr_next"] = 1                                  # b's turn
            st["projects"]["a"]["next_eligible"] = orch.to_iso(
                NOW + datetime.timedelta(hours=2))
            before = dict(st["projects"]["b"])
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["action"], "sleep")
            self.assertEqual(d["sleep_seconds"], 3600)         # until b's window opens
            self.assertEqual(st["projects"]["b"], before)      # no ladder advance

    def test_parked_project_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            st["projects"]["a"]["parked_until"] = orch.to_iso(
                NOW + datetime.timedelta(hours=6))
            d = orch.pick_next(roster, st, NOW)
            self.assertEqual(d["project"]["name"], "b")

    def test_memory_gate_sleeps_short_no_ladder(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            before = json.dumps(st["projects"])
            d = orch.pick_next(roster, st, NOW, mem_mb=2000)   # < 2560 floor
            self.assertEqual(d["action"], "sleep")
            self.assertEqual(d["sleep_seconds"], 300)          # requeue_delay, not ladder
            self.assertIn("memory", d["reason"])
            self.assertEqual(json.dumps(st["projects"]), before)

    def test_run_now_bypasses_eligibility_and_precheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            st["projects"]["b"]["next_eligible"] = orch.to_iso(
                NOW + datetime.timedelta(hours=1))
            d = orch.pick_next(roster, st, NOW, run_now="b")
            self.assertEqual(d["action"], "run")
            self.assertEqual(d["project"]["name"], "b")
            self.assertTrue(d["force_full"])
            self.assertTrue(d["consume_run_now"])

    def test_memory_gate_with_stale_run_now_still_consumes(self):
        # An unknown-name run-now file + low memory must still be consumed,
        # or the driver busy-loops (sleep wakes instantly on the file).
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            d = orch.pick_next(roster, st, NOW, mem_mb=2000, run_now="nope")
            self.assertEqual(d["action"], "sleep")
            self.assertTrue(d["consume_run_now"])

    def test_run_now_unknown_name_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster = self.roster2(tmp)
            st = self.fresh_state(roster)
            d = orch.pick_next(roster, st, NOW, run_now="nope")
            self.assertEqual(d["action"], "run")
            self.assertEqual(d["project"]["name"], "a")   # normal round-robin
            self.assertTrue(d["consume_run_now"])          # still consume the file


class TestClassify(unittest.TestCase):
    OK = {"picked": 0, "pr_opened": 0, "asked": 0, "blocked": 0,
          "progressed": False, "error": None}

    def c(self, **kw):
        base = dict(rc=0, timed_out=False, outcome=dict(self.OK),
                    log_tail=[], questions_count=0)
        base.update(kw)
        return orch.classify_pass(**base)[0]

    def test_timeout_and_nonzero_are_error(self):
        self.assertEqual(self.c(timed_out=True), "error")
        self.assertEqual(self.c(rc=7), "error")

    def test_guillotine_warn_is_error(self):
        tail = ["[ts] WARN: pass terminated background task(s) at the -p ceiling — "
                "a build was likely killed mid-flight ... Background tasks still running"]
        self.assertEqual(self.c(log_tail=tail), "error")

    def test_outcome_error_field_is_error(self):
        o = dict(self.OK); o["error"] = "tracker MCP down"
        self.assertEqual(self.c(outcome=o), "error")

    def test_pr_opened_or_progressed_is_productive(self):
        o = dict(self.OK); o["pr_opened"] = 1
        self.assertEqual(self.c(outcome=o), "productive")
        o = dict(self.OK); o["progressed"] = True
        self.assertEqual(self.c(outcome=o), "productive")

    def test_asked_blocked_or_open_questions_is_waiting(self):
        o = dict(self.OK); o["asked"] = 1
        self.assertEqual(self.c(outcome=o), "waiting")
        o = dict(self.OK); o["blocked"] = 1
        self.assertEqual(self.c(outcome=o), "waiting")
        self.assertEqual(self.c(questions_count=2), "waiting")

    def test_nothing_is_dry(self):
        self.assertEqual(self.c(), "dry")

    def test_missing_outcome_lock_yield_is_skipped_lock(self):
        tail = ["[2026-07-11 12:00:00 UTC] skip: held by interactive pid 4242"]
        self.assertEqual(self.c(outcome=None, log_tail=tail), "skipped-lock")

    def test_missing_outcome_otherwise_dry(self):
        self.assertEqual(self.c(outcome=None), "dry")


class TestApplyOutcome(unittest.TestCase):
    def cfg(self):
        cfg = dict(orch.DEFAULTS)
        cfg["ladder_s"] = [600, 1200, 2400, 3600]
        for k in ("interval", "waiting_interval", "force_full_every",
                  "pass_timeout", "requeue_delay", "crash_park_for"):
            cfg[k + "_s"] = orch.parse_duration(cfg[k])
        for k in ("mem_floor_mb", "error_escalate_after", "crash_park_after"):
            cfg[k] = int(cfg[k])
        return cfg

    def test_productive_resets_everything_to_fast(self):
        ps = orch.default_pstate()
        ps.update(dry_streak=3, error_streak=2, crash_streak=1)
        delay, esc = orch.apply_outcome(ps, "productive", self.cfg(), NOW)
        self.assertEqual(delay, 600)
        self.assertEqual((ps["dry_streak"], ps["error_streak"], ps["crash_streak"]),
                         (0, 0, 0))
        self.assertEqual(ps["next_eligible"], orch.to_iso(
            NOW + datetime.timedelta(seconds=600)))
        self.assertEqual(ps["last_outcome"], "productive")
        self.assertEqual(ps["last_full_pass"], orch.to_iso(NOW))
        self.assertEqual(esc, [])

    def test_dry_ladder_advances_and_caps(self):
        ps = orch.default_pstate()
        cfg = self.cfg()
        delays = [orch.apply_outcome(ps, "dry", cfg, NOW)[0] for _ in range(5)]
        self.assertEqual(delays, [1200, 2400, 3600, 3600, 3600])

    def test_precheck_idle_advances_ladder_but_no_full_pass(self):
        ps = orch.default_pstate()
        delay, _ = orch.apply_outcome(ps, "precheck-idle", self.cfg(), NOW)
        self.assertEqual(delay, 1200)
        self.assertIsNone(ps["last_full_pass"])   # no pass actually ran

    def test_waiting_is_fixed_interval_not_ladder(self):
        ps = orch.default_pstate()
        ps["dry_streak"] = 3
        delay, _ = orch.apply_outcome(ps, "waiting", self.cfg(), NOW)
        self.assertEqual(delay, 1200)              # waiting_interval 20m
        self.assertEqual(ps["dry_streak"], 3)      # ladder untouched

    def test_error_streak_escalates_at_threshold(self):
        ps = orch.default_pstate()
        cfg = self.cfg()
        _, e1 = orch.apply_outcome(ps, "error", cfg, NOW)
        _, e2 = orch.apply_outcome(ps, "error", cfg, NOW)
        self.assertEqual(e1, []); self.assertEqual(e2, [])
        _, e3 = orch.apply_outcome(ps, "error", cfg, NOW)
        self.assertEqual(ps["error_streak"], 3)
        self.assertTrue(any(level == "project" for level, _ in e3))
        self.assertTrue(any(level == "ops" for level, _ in e3))
        # 4th error: streak keeps counting but no repeat spam at the threshold
        _, e4 = orch.apply_outcome(ps, "error", cfg, NOW)
        self.assertEqual(e4, [])

    def test_crash_parks_after_k(self):
        ps = orch.default_pstate()
        cfg = self.cfg()
        orch.apply_outcome(ps, "crash", cfg, NOW)
        orch.apply_outcome(ps, "crash", cfg, NOW)
        self.assertIsNone(ps["parked_until"])
        _, esc = orch.apply_outcome(ps, "crash", cfg, NOW)
        self.assertEqual(ps["crash_streak"], 3)
        self.assertEqual(ps["parked_until"], orch.to_iso(
            NOW + datetime.timedelta(hours=12)))
        self.assertTrue(any(level == "ops" for level, _ in esc))

    def test_skipped_lock_short_requeue_no_streaks(self):
        ps = orch.default_pstate()
        ps["dry_streak"] = 2
        delay, esc = orch.apply_outcome(ps, "skipped-lock", self.cfg(), NOW)
        self.assertEqual(delay, 300)               # requeue_delay 5m
        self.assertEqual(ps["dry_streak"], 2)
        self.assertEqual(esc, [])

    def test_fixed_cadence_uses_interval_for_real_passes(self):
        ps = orch.default_pstate()
        for cls in ("productive", "dry", "waiting"):
            delay, _ = orch.apply_outcome(ps, cls, self.cfg(), NOW,
                                          cadence="fixed", interval_s=2700)
            self.assertEqual(delay, 2700, cls)


class TestCmdRecord(unittest.TestCase):
    """record end-to-end against scratch roster + state files."""

    def run_record(self, tmp, outcome, project="alpha"):
        roster_path = make_roster_dir(tmp)
        state_path = Path(tmp) / "orch-state.json"
        rc = orch.main(["record", "--roster", str(roster_path),
                        "--state", str(state_path), "--project", project,
                        "--outcome", outcome, "--now", "2026-07-11T12:00:00Z"])
        return rc, json.loads(state_path.read_text())

    def test_record_persists_and_advances_rr(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, st = self.run_record(tmp, "productive")
        self.assertEqual(rc, 0)
        ps = st["projects"]["alpha"]
        self.assertEqual(ps["last_outcome"], "productive")
        self.assertEqual(st["rr_next"], 1 % 1)   # single project → wraps to 0
        self.assertNotIn("pass_started", st)

    def test_record_clears_write_ahead(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = make_roster_dir(tmp)
            state_path = Path(tmp) / "orch-state.json"
            st = {"pass_started": {"project": "alpha", "ts": "2026-07-11T11:00:00Z"}}
            orch.save_state(state_path, st)
            orch.main(["record", "--roster", str(roster_path),
                       "--state", str(state_path), "--project", "alpha",
                       "--outcome", "dry", "--now", "2026-07-11T12:00:00Z"])
            st = json.loads(state_path.read_text())
        self.assertNotIn("pass_started", st)

    def test_unknown_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                self.run_record(tmp, "meh")


class TestStartup(unittest.TestCase):
    def test_crash_recovery_and_lock_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = make_roster_dir(tmp)
            state_path = Path(tmp) / "orch-state.json"
            lock = Path(tmp) / "state-alpha" / "loop.lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text("42")
            orch.save_state(state_path, {
                "pass_started": {"project": "alpha", "ts": "2026-07-11T11:00:00Z"}})
            rc = orch.main(["startup", "--roster", str(roster_path),
                            "--state", str(state_path),
                            "--now", "2026-07-11T12:00:00Z"])
            self.assertEqual(rc, 0)
            self.assertFalse(lock.exists())          # lock-clear on boot
            st = json.loads(state_path.read_text())
            self.assertNotIn("pass_started", st)
            self.assertEqual(st["projects"]["alpha"]["crash_streak"], 1)
            self.assertEqual(st["projects"]["alpha"]["last_outcome"], "crash")

    def test_guard_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = make_roster_dir(tmp)
            os.remove(Path(tmp) / "alpha" / ".dw-agent-clone")   # break the guard
            with self.assertRaises(SystemExit):
                orch.main(["startup", "--roster", str(roster_path),
                           "--state", str(Path(tmp) / "orch-state.json")])

    def test_clean_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = make_roster_dir(tmp)
            state_path = Path(tmp) / "orch-state.json"
            rc = orch.main(["startup", "--roster", str(roster_path),
                            "--state", str(state_path)])
            self.assertEqual(rc, 0)
            st = json.loads(state_path.read_text())
            self.assertIn("alpha", st["projects"])


class TestPassStart(unittest.TestCase):
    def test_write_ahead_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = make_roster_dir(tmp)
            state_path = Path(tmp) / "orch-state.json"
            rc = orch.main(["pass-start", "--roster", str(roster_path),
                            "--state", str(state_path), "--project", "alpha",
                            "--now", "2026-07-11T12:00:00Z"])
            self.assertEqual(rc, 0)
            st = json.loads(state_path.read_text())
            self.assertEqual(st["pass_started"],
                             {"project": "alpha", "ts": "2026-07-11T12:00:00Z"})


if __name__ == "__main__":
    unittest.main()
