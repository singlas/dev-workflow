# Ticket-Loop Central Round-Robin Orchestrator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One long-lived orchestrator process that round-robins N ticket-loop projects sequentially with an adaptive pre-check + backoff cadence, wrapping the *unchanged* per-pass runner (`run-pass.sh` → `cron-run.sh` → `claude -p /ticket-loop`), with the supervision blockers (per-pass timeout, error classification + escalation, crash write-ahead, lock-clear on boot, memory headroom gate, work-tree marker guard) built in from day one.

**Architecture:** Approach A from the spec (`docs/superpowers/specs/2026-07-11-ticket-loop-orchestrator-design.md`) — a thin bash driver (`orchestrator.sh`, PID 1 in the container) owns process concerns (signals, process-group timeout, secret-scoped child env, Telegram escalation), and a stdlib+PyYAML Python brain (`orch.py`) owns all scheduling state and math (roster, ladder, windows, classification, write-ahead), matching the `telegram.py` idiom. The pre-check is `queue-count.py` (Linear GraphQL, tracker-adapter seam) + the free `state.json` questions map + a read-only `telegram.py peek`. The skill emits a structured `outcome.json` per pass; the orchestrator classifies from it.

**Tech Stack:** bash, Python 3.9+ stdlib (+ PyYAML for YAML files, present in the container via `python3-yaml` and on laptops via `uv run` PEP 723), `unittest`, Docker (existing `skills/ticket-loop/docker/Dockerfile`).

## Global Constraints

- All four axes stay composable: the orchestrator is **additive**; the single-project shapes (interactive `/loop`, `install-cron.sh` timer, containerized single-pass) are untouched and stay first-class.
- Cadence is per-roster with per-project override: `adaptive` (pre-check + ladder) or `fixed` (constant interval, **no pre-check, no ladder**).
- Backoff ladder default: `10m → 20m → 40m → cap 60m`. Productive resets to 10m. Waiting-on-human uses its own fixed interval (default `20m`). Errors are **never** classified dry.
- Per-pass timeout default `90m` (kill the **process group**, classify **error**).
- Host-memory headroom gate: skip the turn when `/proc/meminfo` `MemAvailable < 2560 MB` (short requeue, **no** ladder advance). On non-Linux (no `/proc/meminfo`) the gate is skipped.
- Work-tree guard is a **positive allowlist**: every roster `work_tree` must resolve under the roster `root` **and** contain a `.dw-agent-clone` marker file; otherwise startup hard-fails.
- Forced unconditional safety pass per project every `8h` (default; spec range 6–12h) regardless of pre-check.
- Lock-clear on boot: orchestrator startup removes every roster project's `loop.lock`. A pass skipped because an interactive session holds the lock is **skipped-lock**, not dry (short requeue, no ladder advance).
- Window precedence: roster entry `window` ∩ repo `dev-workflow.yml` `schedule.window` (tighten-only). A window skip does **not** advance the ladder.
- Secret scoping: the orchestrator process holds **no** project secrets; each pass/pre-check child sources only its own `DW_ENV_FILE`.
- New Python must pass `python3 -m py_compile`; tests are stdlib `unittest` files runnable as `python3 <file>` (idiom: `test_telegram.py`). Bash must pass `bash -n`.
- Deferred (per spec, NOT in this plan): SIGHUP roster reload, status-dashboard polish, `last-batch.json` wiring, rate-limit-pool confirmation.

**Two deliberate deviations from the spec's wording (both flagged for review):**
1. Spec §6 says "CMD becomes the orchestrator". The existing `agent.service.template` runs the image with **no command** (relies on default CMD = `run-pass.sh`), so swapping CMD would silently turn every existing single-pass timer deployment into a daemon — violating the spec's own non-deprecation principle. **CMD stays `run-pass.sh`**; the orchestrator is started with an explicit command (`docker run … /opt/dev-workflow/bin/orchestrator.sh`), documented in the new README.
2. Supervision §8 says "extend the existing `ticket-loop status` subcommand" — that subcommand lives in `install-cron.sh` and is macOS-launchd-specific (`plutil`, `launchctl`). The orchestrator gets its own `orch.py status` subcommand instead (works in-container via `docker exec`); `install-cron.sh` is untouched.

## File Structure

```
skills/ticket-loop/orchestrator/          # NEW — the mode axis
├── orch.py                # scheduling brain: roster, state, ladder, windows,
│                          #   classify, record, startup/write-ahead, status
├── orchestrator.sh        # PID-1 driver: signals, timeout, pre-check, exec, alerts
├── roster.example.yml     # annotated roster config
├── test_orch.py           # stdlib unittest for orch.py (offline)
├── test_orchestrator_smoke.sh  # one offline end-to-end turn with a stub runner
└── README.md              # deployment (nt/docker), rollout, onboarding checklist
dev-workflow/
├── queue-count.py         # NEW — Linear queue-depth pre-check (adapter seam)
└── test_queue_count.py    # NEW — offline tests (query build + response parse)
skills/ticket-loop/
├── telegram.py            # MODIFY — add read-only `peek` subcommand
├── test_telegram.py       # MODIFY — peek tests
├── cron-run.sh            # MODIFY — delete stale outcome.json before each pass
├── SKILL.md               # MODIFY — the pass-outcome contract (outcome.json)
├── README.md              # MODIFY — pointer to the orchestrator
└── docker/
    ├── Dockerfile         # MODIFY — bake orchestrator + queue-count.py
    └── local-run.sh       # MODIFY — seed writes the .dw-agent-clone marker
dev-workflow/tracker-adapters.md  # MODIFY — queue_count verb row (one source of truth)
CLAUDE.md                  # MODIFY — repo tree + conventions mention
```

All work happens on branch `worktree-ticket-loop-orchestrator` in this worktree. Run tests from the repo root.

---

### Task 1: `orch.py` foundations — durations, roster load + marker guard, state I/O

**Files:**
- Create: `skills/ticket-loop/orchestrator/orch.py`
- Test: `skills/ticket-loop/orchestrator/test_orch.py`

**Interfaces:**
- Produces (later tasks import these exact names from `orch.py`):
  - `parse_duration(v) -> int` (seconds; accepts `int` or `"30m"`-style `s/m/h/d` strings; raises `RosterError`)
  - `class RosterError(Exception)`
  - `load_roster(path) -> dict` — `{"root": str, "cfg": dict, "projects": [dict]}`; each project dict has keys `name, work_tree, env_file, state_dir, model, tz, window, cadence, interval_s`; `cfg` has `ladder_s: [int], interval_s, waiting_interval_s, force_full_every_s, pass_timeout_s, requeue_delay_s, crash_park_for_s: int`, `mem_floor_mb, error_escalate_after, crash_park_after: int`, `cadence: str`
  - `check_work_tree(project, root) -> None` (raises `RosterError` on guard failure)
  - `load_state(path) -> dict`, `save_state(path, st) -> None` (atomic), `ensure_projects(st, projects) -> None`, `default_pstate() -> dict`
  - `now_utc() -> datetime`, `to_iso(dt) -> str`, `from_iso(s) -> datetime`
  - `mem_available_mb(path="/proc/meminfo") -> int|None`

- [ ] **Step 1: Write the failing tests**

Create `skills/ticket-loop/orchestrator/test_orch.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: FAIL at import time (`orch.py` does not exist).

- [ ] **Step 3: Write the implementation**

Create `skills/ticket-loop/orchestrator/orch.py`:

```python
#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Scheduling brain for the ticket-loop orchestrator (mode axis: multi-project).

orchestrator.sh (the PID-1 driver) shells into this for every decision; all
roster/backoff/window/classification state lives here so it is unit-testable
offline. Stdlib + PyYAML (python3-yaml in the container; `uv run` supplies it
on a laptop via the PEP 723 header above).

Subcommands (see cmd_* below; --sh prints shell-eval-able KEY=VALUE lines for
the driver, the default prints JSON for humans/tests):
  startup     validate roster (marker-file allowlist guard, §8), recover the
              crash write-ahead record, clear every project's stale loop.lock
  next        pick the next action: run one project, or sleep
  pass-start  persist the crash write-ahead record before a pass launches
  classify    classify a finished pass: productive|dry|waiting|error|skipped-lock
  record      apply a pass outcome to the project's backoff state
  status      human-readable status table

State file (orch-state.json, atomic writes):
  {"projects": {name: {dry_streak, error_streak, crash_streak, next_eligible,
                       last_pass, last_full_pass, last_outcome, parked_until}},
   "rr_next": int, "pass_started": {"project": name, "ts": iso} | absent,
   "all_error_alerted": bool}
"""

import argparse
import datetime
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # surfaced as a RosterError at load time, not an import crash
    yaml = None


class RosterError(Exception):
    """Invalid roster / config — the orchestrator must refuse to run."""


# ── time helpers ──────────────────────────────────────────────────────────────

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def to_iso(dt):
    return dt.replace(microsecond=0).astimezone(datetime.timezone.utc) \
             .isoformat().replace("+00:00", "Z")


def from_iso(s):
    return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


_DUR_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(v):
    """'10m' / '8h' / '45s' / '1d' / bare int (seconds) → seconds."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    m = _DUR_RE.match(str(v))
    if not m:
        raise RosterError(f"bad duration: {v!r} (want e.g. 45s, 10m, 8h, 1d)")
    return int(m.group(1)) * _UNITS[m.group(2) or "s"]


# ── roster ────────────────────────────────────────────────────────────────────

DEFAULTS = {
    "cadence": "adaptive",
    "interval": "30m",              # fixed-cadence gap
    "ladder": ["10m", "20m", "40m", "60m"],
    "waiting_interval": "20m",      # waiting-on-human: neither ladder nor fast
    "force_full_every": "8h",       # unconditional safety pass (supervision §6)
    "pass_timeout": "90m",          # per-pass process-group timeout (blocker §1)
    "requeue_delay": "5m",          # skipped-lock / low-memory requeue
    "mem_floor_mb": 2560,           # host MemAvailable floor (§Capacity)
    "error_escalate_after": 3,      # consecutive errors → escalate (blocker §2)
    "crash_park_after": 3,          # consecutive crashes → park (blocker §3)
    "crash_park_for": "12h",
}

_REQUIRED_PROJECT_KEYS = ("name", "work_tree", "env_file", "state_dir")
_DURATION_KEYS = ("interval", "waiting_interval", "force_full_every",
                  "pass_timeout", "requeue_delay", "crash_park_for")


def load_roster(path):
    if yaml is None:
        raise RosterError("PyYAML is required to read the roster "
                          "(apt: python3-yaml, or run via `uv run`)")
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RosterError(f"cannot read roster {path}: {exc}")
    projects = raw.get("projects")
    if not isinstance(projects, list) or not projects:
        raise RosterError(f"{path}: `projects` must be a non-empty list")
    cfg = {k: raw.get(k, d) for k, d in DEFAULTS.items()}
    if not isinstance(cfg["ladder"], list) or not cfg["ladder"]:
        raise RosterError("`ladder` must be a non-empty list of durations")
    cfg["ladder_s"] = [parse_duration(x) for x in cfg["ladder"]]
    for k in _DURATION_KEYS:
        cfg[k + "_s"] = parse_duration(cfg[k])
    for k in ("mem_floor_mb", "error_escalate_after", "crash_park_after"):
        cfg[k] = int(cfg[k])
    if cfg["cadence"] not in ("adaptive", "fixed"):
        raise RosterError(f"cadence must be adaptive|fixed, not {cfg['cadence']!r}")
    root = str(raw.get("root") or Path(path).resolve().parent)
    out, seen = [], set()
    for entry in projects:
        if not isinstance(entry, dict):
            raise RosterError(f"bad project entry (not a mapping): {entry!r}")
        for req in _REQUIRED_PROJECT_KEYS:
            if not entry.get(req):
                raise RosterError(f"project entry missing `{req}`: {entry!r}")
        name = str(entry["name"])
        if name in seen:
            raise RosterError(f"duplicate project name: {name}")
        seen.add(name)
        cadence = entry.get("cadence", cfg["cadence"])
        if cadence not in ("adaptive", "fixed"):
            raise RosterError(f"{name}: cadence must be adaptive|fixed")
        out.append({
            "name": name,
            "work_tree": str(entry["work_tree"]),
            "env_file": str(entry["env_file"]),
            "state_dir": str(entry["state_dir"]),
            "model": entry.get("model"),
            "tz": entry.get("tz"),
            "window": entry.get("window"),
            "cadence": cadence,
            "interval_s": parse_duration(entry.get("interval", cfg["interval"])),
        })
    return {"root": root, "cfg": cfg, "projects": out}


def check_work_tree(project, root):
    """Spec §8 guard — a positive allowlist, not a path denylist: the work tree
    must resolve strictly under the orchestrator's own volume root AND carry the
    `.dw-agent-clone` marker written at seed time. Whitelists orchestrator-owned
    clones so a bind-mounted prod checkout can never be roster-driven."""
    wt = Path(project["work_tree"]).resolve()
    rootp = Path(root).resolve()
    try:
        rel = wt.relative_to(rootp)
    except ValueError:
        raise RosterError(f"{project['name']}: work tree {wt} is outside the "
                          f"roster root {rootp} — refusing")
    if str(rel) in ("", "."):
        raise RosterError(f"{project['name']}: work tree must be a directory "
                          f"UNDER the roster root, not the root itself")
    if not (wt / ".dw-agent-clone").exists():
        raise RosterError(f"{project['name']}: work tree {wt} has no "
                          ".dw-agent-clone marker — only dedicated agent clones "
                          "may be roster-driven (touch the marker at seed time)")


# ── orch-state ────────────────────────────────────────────────────────────────

def default_pstate():
    return {"dry_streak": 0, "error_streak": 0, "crash_streak": 0,
            "next_eligible": None, "last_pass": None, "last_full_pass": None,
            "last_outcome": None, "parked_until": None}


def load_state(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        # Corrupt mid-write state (should be impossible with atomic saves) —
        # quarantine and restart from scratch rather than dying forever.
        p.rename(p.with_suffix(".json.corrupt"))
        return {}


def save_state(path, st):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    tmp.replace(p)  # atomic — same pattern as telegram.py save_state()


def ensure_projects(st, projects):
    known = {p["name"] for p in projects}
    st.setdefault("projects", {})
    for p in projects:
        st["projects"].setdefault(p["name"], default_pstate())
    for name in list(st["projects"]):
        if name not in known:
            del st["projects"][name]
    st.setdefault("rr_next", 0)


# ── host memory gate ──────────────────────────────────────────────────────────

def mem_available_mb(path="/proc/meminfo"):
    """MemAvailable in MB, or None when unreadable (non-Linux → gate skipped)."""
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


# ── CLI (subcommands are added in later tasks) ────────────────────────────────

def emit(args, pairs):
    """Print a result: shell-eval-able KEY=VALUE lines with --sh, else JSON."""
    if getattr(args, "sh", False):
        for k, v in pairs.items():
            print(f"{k}={shlex.quote('' if v is None else str(v))}")
    else:
        print(json.dumps(pairs, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    # Subcommands are registered here by later tasks.
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: all tests PASS (OK).

Run: `python3 -m py_compile skills/ticket-loop/orchestrator/orch.py && echo COMPILED`
Expected: `COMPILED`.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/orchestrator/orch.py skills/ticket-loop/orchestrator/test_orch.py
git commit -m "feat(orchestrator): orch.py foundations — roster load, marker-file work-tree guard, atomic orch-state, memory gate"
```

---

### Task 2: Windows + the `next` decision (round-robin pick, memory gate, run-now, force-full)

**Files:**
- Modify: `skills/ticket-loop/orchestrator/orch.py` (add window helpers + `pick_next` + `cmd_next`)
- Test: `skills/ticket-loop/orchestrator/test_orch.py` (append test classes)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces:
  - `parse_window(s) -> (int, int)` (minutes-of-day start/end; raises `RosterError`)
  - `minute_in_window(t, w) -> bool` (handles overnight wrap; equal endpoints = always open)
  - `read_repo_schedule(work_tree) -> dict` (`{"window":…, "tz":…}` from `<work_tree>/dev-workflow.yml`, `{}` when absent/unreadable)
  - `windows_for(project) -> (list_of_windows, tz_name_or_None)` (roster window ∩ repo window; tz = roster `tz` else repo `schedule.tz`)
  - `seconds_until_open(wins, tz, now) -> int|None` (0 = open now; None = empty intersection)
  - `pick_next(roster, st, now, mem_mb=None, run_now=None) -> dict` — `{"action": "run"|"sleep", …}`; run dicts carry `project` (the full project dict), `force_full: bool`, `precheck: bool`, `consume_run_now: bool`
  - CLI: `orch.py next --roster R --state F [--now ISO] [--run-now NAME] [--sh]` — `--sh` prints `ACTION/PROJECT/WORK_TREE/ENV_FILE/STATE_DIR/MODEL/PROJECT_TZ/CADENCE/PRECHECK/FORCE_FULL/TIMEOUT_S/CONSUME_RUN_NOW` for run, `ACTION/SLEEP_S/REASON` for sleep.

- [ ] **Step 1: Write the failing tests** (append to `test_orch.py`, before the `__main__` block)

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: FAIL with `AttributeError: module 'orch_mod' has no attribute 'parse_window'` (Task 1 tests still pass).

- [ ] **Step 3: Implement** (insert into `orch.py` after the memory-gate section, before the CLI section; register the subcommand in `main`)

```python
# ── schedule windows (supervision §9: roster ∩ repo, tighten-only) ────────────

_WIN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def parse_window(s):
    m = _WIN_RE.match(str(s))
    if not m:
        raise RosterError(f"bad window: {s!r} (want HH:MM-HH:MM)")
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise RosterError(f"bad window: {s!r} (hours 0-23, minutes 0-59)")
    return (h1 * 60 + m1, h2 * 60 + m2)


def minute_in_window(t, w):
    a, b = w
    if a == b:            # degenerate — treat as always open
        return True
    if a < b:
        return a <= t < b
    return t >= a or t < b  # overnight wrap, e.g. 22:00-06:00


def read_repo_schedule(work_tree):
    """The repo's own schedule gate: dev-workflow.yml schedule.{window,tz}.
    Missing file / unparseable → {} (no repo gate)."""
    f = Path(work_tree) / "dev-workflow.yml"
    if not f.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(f.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    sched = data.get("schedule") or {}
    out = {}
    if sched.get("window"):
        out["window"] = sched["window"]
    if sched.get("tz"):
        out["tz"] = sched["tz"]
    return out


def windows_for(project):
    """All gating windows for a project (roster entry + repo config — a time must
    be inside BOTH: the intersection, consistent with boundary rule 1), plus the
    tz they're evaluated in (roster tz beats repo schedule.tz)."""
    wins = []
    if project.get("window"):
        wins.append(parse_window(project["window"]))
    repo = read_repo_schedule(project["work_tree"])
    if repo.get("window"):
        wins.append(parse_window(repo["window"]))
    return wins, (project.get("tz") or repo.get("tz"))


def _local_minute(now, tz_name):
    if tz_name:
        from zoneinfo import ZoneInfo
        loc = now.astimezone(ZoneInfo(tz_name))
    else:
        loc = now.astimezone()
    return loc.hour * 60 + loc.minute


def seconds_until_open(wins, tz_name, now):
    """0 when `now` is inside every window; else seconds until the first minute
    inside all of them (scanned over 48h); None when the intersection is empty."""
    if not wins:
        return 0
    t0 = _local_minute(now, tz_name)
    for k in range(0, 2880):
        t = (t0 + k) % 1440
        if all(minute_in_window(t, w) for w in wins):
            return k * 60
    return None


# ── the `next` decision ───────────────────────────────────────────────────────

def _parked(ps, now):
    pu = ps.get("parked_until")
    return bool(pu) and now < from_iso(pu)


def pick_next(roster, st, now, mem_mb=None, run_now=None):
    """Choose the next action. Read-only on `st` (record() owns all mutation) —
    EXCEPT nothing: window skips deliberately do not touch backoff state."""
    cfg = roster["cfg"]
    projs = roster["projects"]

    if run_now is not None:
        target = next((p for p in projs if p["name"] == run_now), None)
        if target is None and run_now == "":
            target = projs[0]
        if target is not None and not _parked(st["projects"][target["name"]], now):
            return {"action": "run", "project": target, "force_full": True,
                    "precheck": False, "consume_run_now": True}
        # unknown/parked name: consume the file (driver deletes it) and fall through

    if mem_mb is not None and mem_mb < cfg["mem_floor_mb"]:
        # consume_run_now here too: an unknown-name run-now file that fell
        # through must still be deleted, or the driver busy-loops on it.
        return {"action": "sleep", "sleep_seconds": cfg["requeue_delay_s"],
                "reason": f"low memory: {mem_mb} MB available "
                          f"< {cfg['mem_floor_mb']} MB floor",
                "consume_run_now": run_now is not None}

    waits = []
    start = st.get("rr_next", 0) % len(projs)
    for i in range(len(projs)):
        p = projs[(start + i) % len(projs)]
        ps = st["projects"][p["name"]]
        if _parked(ps, now):
            waits.append((from_iso(ps["parked_until"]) - now).total_seconds())
            continue
        ne = ps.get("next_eligible")
        if ne and now < from_iso(ne):
            waits.append((from_iso(ne) - now).total_seconds())
            continue
        wins, tz = windows_for(p)
        wait = seconds_until_open(wins, tz, now)
        if wait is None:          # empty intersection — startup already warned
            waits.append(86400)
            continue
        if wait > 0:              # outside the window: skip, NO ladder advance
            waits.append(wait)
            continue
        lfp = ps.get("last_full_pass")
        force_full = (lfp is None or
                      (now - from_iso(lfp)).total_seconds() >= cfg["force_full_every_s"])
        precheck = p["cadence"] == "adaptive" and not force_full
        return {"action": "run", "project": p, "force_full": force_full,
                "precheck": precheck,
                "consume_run_now": run_now is not None}
    sleep_s = int(min(waits)) if waits else 60
    return {"action": "sleep", "sleep_seconds": max(30, min(sleep_s, 3600)),
            "reason": "no project eligible",
            "consume_run_now": run_now is not None}


def cmd_next(args):
    roster = load_roster(args.roster)
    st = load_state(args.state)
    ensure_projects(st, roster["projects"])
    now = from_iso(args.now) if args.now else now_utc()
    d = pick_next(roster, st, now, mem_mb=mem_available_mb(),
                  run_now=args.run_now)
    save_state(args.state, st)   # persists newly-ensured project entries
    if d["action"] == "sleep":
        emit(args, {"ACTION": "sleep", "SLEEP_S": d["sleep_seconds"],
                    "REASON": d["reason"],
                    "CONSUME_RUN_NOW": 1 if d.get("consume_run_now") else 0})
        return 0
    p = d["project"]
    emit(args, {"ACTION": "run", "PROJECT": p["name"],
                "WORK_TREE": p["work_tree"], "ENV_FILE": p["env_file"],
                "STATE_DIR": p["state_dir"], "MODEL": p["model"] or "",
                "PROJECT_TZ": p["tz"] or "", "CADENCE": p["cadence"],
                "PRECHECK": 1 if d["precheck"] else 0,
                "FORCE_FULL": 1 if d["force_full"] else 0,
                "TIMEOUT_S": roster["cfg"]["pass_timeout_s"],
                "CONSUME_RUN_NOW": 1 if d.get("consume_run_now") else 0})
    return 0
```

And in `main()`, replace the `# Subcommands are registered here by later tasks.` comment with:

```python
    def common(p, state=True):
        p.add_argument("--roster", required=True)
        if state:
            p.add_argument("--state", required=True, help="orch-state.json path")
        p.add_argument("--now", help="ISO timestamp override (tests)")
        p.add_argument("--sh", action="store_true",
                       help="print shell-eval-able KEY=VALUE lines")

    p_next = sub.add_parser("next", help="pick the next action")
    common(p_next)
    p_next.add_argument("--run-now", default=None,
                        help="project name from the run-now trigger file "
                             "('' = first roster project)")
    p_next.set_defaults(func=cmd_next)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/orchestrator/orch.py skills/ticket-loop/orchestrator/test_orch.py
git commit -m "feat(orchestrator): window intersection + round-robin next-decision with memory gate, run-now, forced safety pass"
```

---

### Task 3: Outcome classification + `record` backoff transitions + escalations

**Files:**
- Modify: `skills/ticket-loop/orchestrator/orch.py`
- Test: `skills/ticket-loop/orchestrator/test_orch.py` (append)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `classify_pass(rc, timed_out, outcome, log_tail, questions_count) -> (cls, reason)` — `cls ∈ {"productive","dry","waiting","error","skipped-lock"}`; `outcome` is the parsed `outcome.json` dict or `None`; `log_tail` is a list of log lines.
  - `apply_outcome(ps, cls, cfg, now, cadence="adaptive", interval_s=None) -> (delay_s, escalations)` — mutates the per-project state dict `ps`; `escalations` is a list of `(level, message)` with `level ∈ {"project","ops"}`; accepts additionally `cls ∈ {"precheck-idle","crash"}`.
  - CLI: `orch.py classify --state-dir D --rc N [--timed-out]` — prints `"<cls> <reason>"` on one line.
  - CLI: `orch.py record --roster R --state F --project P --outcome CLS [--now ISO] [--sh]` — applies the outcome, advances `rr_next` past P, clears `pass_started`, fires the all-projects-erroring check; `--sh` prints `NEXT_ELIGIBLE`, `ESCALATE_PROJECT`, `ESCALATE_OPS`.
  - The `outcome.json` contract (written by the skill, Task 7): `{"picked": int, "pr_opened": int, "asked": int, "blocked": int, "progressed": bool, "error": str|null}`.

- [ ] **Step 1: Write the failing tests** (append to `test_orch.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: FAIL with `AttributeError` on `classify_pass` (earlier tests still pass).

- [ ] **Step 3: Implement** (insert into `orch.py` after `pick_next`/`cmd_next`)

```python
# ── outcome classification (spec §4 — four classes, never silently dry) ──────

OUTCOME_CLASSES = ("productive", "dry", "precheck-idle", "waiting",
                   "error", "crash", "skipped-lock")


def classify_pass(rc, timed_out, outcome, log_tail, questions_count):
    """Classify one finished pass. `outcome` is the skill-emitted outcome.json
    dict (None when the pass never wrote one — cron-run.sh deletes the stale
    file pre-pass, so a present file is always THIS pass's line)."""
    if timed_out:
        return "error", "pass hit the orchestrator timeout"
    if rc != 0:
        return "error", f"pass exited {rc}"
    if any("Background tasks still running" in line for line in log_tail):
        return "error", "background-guillotine WARN (a build was likely killed)"
    if outcome is None:
        if any("skip:" in line for line in log_tail[-3:]):
            # cron-run.sh yielded the singleton lock — actively worked, not dry
            return "skipped-lock", "runner yielded the singleton lock"
        return "dry", "no outcome.json written (counting as dry)"
    if outcome.get("error"):
        return "error", f"pass reported: {outcome['error']}"
    if outcome.get("pr_opened", 0) > 0 or outcome.get("progressed"):
        return "productive", "PR opened / ticket advanced"
    if outcome.get("asked", 0) > 0 or outcome.get("blocked", 0) > 0:
        return "waiting", "question asked / ticket blocked on a human"
    if questions_count > 0:
        return "waiting", f"{questions_count} question(s) still open"
    return "dry", "ran, nothing to do"


def cmd_classify(args):
    sd = Path(args.state_dir)
    outcome = None
    f = sd / "outcome.json"
    if f.exists():
        try:
            outcome = json.loads(f.read_text())
        except json.JSONDecodeError:
            outcome = None
    tail = []
    log = sd / "logs" / "ticket-loop-cron.log"
    if log.exists():
        tail = log.read_text().splitlines()[-15:]
    questions = 0
    state_json = sd / "state.json"
    if state_json.exists():
        try:
            questions = len(json.loads(state_json.read_text()).get("questions") or {})
        except json.JSONDecodeError:
            pass
    cls, reason = classify_pass(args.rc, args.timed_out, outcome, tail, questions)
    print(f"{cls} {reason}")
    return 0


# ── backoff transitions (spec §4 + supervision §2/§3) ─────────────────────────

def apply_outcome(ps, cls, cfg, now, cadence="adaptive", interval_s=None):
    """Mutate one project's backoff state for a classified outcome; return
    (delay_seconds, [(level, message)]). Ladder indexes by streak so
    productive→10m, 1st dry→20m, 2nd→40m, then the 60m cap."""
    if cls not in OUTCOME_CLASSES:
        raise ValueError(f"unknown outcome class: {cls}")
    ladder = cfg["ladder_s"]
    esc = []

    def rung(streak):
        return ladder[min(streak, len(ladder) - 1)]

    real_pass = cls in ("productive", "dry", "waiting", "error")
    if cls == "productive":
        ps["dry_streak"] = ps["error_streak"] = ps["crash_streak"] = 0
        delay = ladder[0]
    elif cls in ("dry", "precheck-idle"):
        ps["dry_streak"] += 1
        ps["error_streak"] = 0
        delay = rung(ps["dry_streak"])
    elif cls == "waiting":
        # Neither the ladder nor "productive": polling faster doesn't make
        # humans answer faster, and an ignored question must not pin fast cadence.
        ps["error_streak"] = 0
        delay = cfg["waiting_interval_s"]
    elif cls == "error":
        ps["error_streak"] += 1
        delay = rung(ps["error_streak"])
        if ps["error_streak"] == cfg["error_escalate_after"]:
            msg = (f"⚠️ ticket-loop: {ps['error_streak']} consecutive failed "
                   f"passes — check the loop log")
            esc.append(("project", msg))
            esc.append(("ops", msg))
    elif cls == "crash":
        ps["crash_streak"] += 1
        ps["error_streak"] += 1
        delay = rung(ps["crash_streak"])
        if ps["crash_streak"] >= cfg["crash_park_after"]:
            ps["parked_until"] = to_iso(
                now + datetime.timedelta(seconds=cfg["crash_park_for_s"]))
            esc.append(("ops", f"🚨 parked after {ps['crash_streak']} consecutive "
                               f"crashes (until {ps['parked_until']}) — investigate "
                               "before it rejoins the roster"))
    else:  # skipped-lock — an interactive session is working the project
        delay = cfg["requeue_delay_s"]
    if cadence == "fixed" and real_pass and interval_s:
        delay = interval_s
    ps["next_eligible"] = to_iso(now + datetime.timedelta(seconds=delay))
    ps["last_outcome"] = cls
    if real_pass:
        ps["last_pass"] = to_iso(now)
        ps["last_full_pass"] = to_iso(now)
    return delay, esc


def cmd_record(args):
    roster = load_roster(args.roster)
    st = load_state(args.state)
    ensure_projects(st, roster["projects"])
    now = from_iso(args.now) if args.now else now_utc()
    names = [p["name"] for p in roster["projects"]]
    if args.project not in names:
        sys.exit(f"error: unknown project {args.project!r}")
    if args.outcome not in OUTCOME_CLASSES:
        sys.exit(f"error: unknown outcome {args.outcome!r} "
                 f"(one of {', '.join(OUTCOME_CLASSES)})")
    proj = next(p for p in roster["projects"] if p["name"] == args.project)
    ps = st["projects"][args.project]
    _delay, esc = apply_outcome(ps, args.outcome, roster["cfg"], now,
                                cadence=proj["cadence"],
                                interval_s=proj["interval_s"])
    st.pop("pass_started", None)                       # write-ahead consumed
    st["rr_next"] = (names.index(args.project) + 1) % len(names)
    # Shared-failure heuristic (supervision §2): one ~/.claude for all projects,
    # so an expired OAuth token errors everyone at once — say so loudly, once.
    all_err = (len(names) > 1 and
               all(st["projects"][n]["error_streak"] >= 1 for n in names))
    if all_err and args.outcome in ("error", "crash") and not st.get("all_error_alerted"):
        st["all_error_alerted"] = True
        esc.append(("ops", "🚨 EVERY roster project is erroring — shared-auth "
                           "failure likely (expired CLAUDE_CODE_OAUTH_TOKEN in "
                           "the shared ~/.claude?)"))
    if not all_err:
        st["all_error_alerted"] = False
    save_state(args.state, st)
    emit(args, {
        "NEXT_ELIGIBLE": ps["next_eligible"],
        "ESCALATE_PROJECT": "; ".join(m for lvl, m in esc if lvl == "project"),
        "ESCALATE_OPS": "; ".join(m for lvl, m in esc if lvl == "ops"),
    })
    return 0
```

And register in `main()` (after the `next` parser):

```python
    p_cls = sub.add_parser("classify", help="classify a finished pass")
    p_cls.add_argument("--state-dir", required=True)
    p_cls.add_argument("--rc", type=int, required=True)
    p_cls.add_argument("--timed-out", action="store_true")
    p_cls.set_defaults(func=cmd_classify)

    p_rec = sub.add_parser("record", help="apply a pass outcome to backoff state")
    common(p_rec)
    p_rec.add_argument("--project", required=True)
    p_rec.add_argument("--outcome", required=True)
    p_rec.set_defaults(func=cmd_record)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/orchestrator/orch.py skills/ticket-loop/orchestrator/test_orch.py
git commit -m "feat(orchestrator): four-class outcome classification + backoff transitions with error/crash escalation"
```

---

### Task 4: `startup` (crash write-ahead recovery, lock-clear), `pass-start`, `status`

**Files:**
- Modify: `skills/ticket-loop/orchestrator/orch.py`
- Test: `skills/ticket-loop/orchestrator/test_orch.py` (append)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - CLI `orch.py startup --roster R --state F [--now ISO] [--sh]` — validates roster + work-tree guard (exit 1 + stderr `FATAL: …` on failure), recovers a `pass_started` write-ahead as a **crash** outcome, removes every project's `<state_dir>/loop.lock`, persists. `--sh` prints `PROJECTS` (space-joined names), `CRASH_RECOVERED` (name or empty), `LOCKS_CLEARED` (space-joined paths or empty), `ESCALATE_OPS`.
  - CLI `orch.py pass-start --roster R --state F --project P [--now ISO]` — persists `st["pass_started"] = {"project": P, "ts": iso}`.
  - CLI `orch.py status --roster R --state F` — human-readable table (also serves observability §8: `pass_started` doubles as the `current` record).

- [ ] **Step 1: Write the failing tests** (append to `test_orch.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: new tests FAIL (`invalid choice: 'startup'` / SystemExit 2 from argparse).

- [ ] **Step 3: Implement** (insert into `orch.py` after `cmd_record`)

```python
# ── startup / write-ahead / status (supervision §3, §5, §8) ───────────────────

def cmd_startup(args):
    try:
        roster = load_roster(args.roster)
        for p in roster["projects"]:
            check_work_tree(p, roster["root"])
    except RosterError as exc:
        sys.exit(f"FATAL: {exc}")
    now = from_iso(args.now) if args.now else now_utc()
    st = load_state(args.state)
    ensure_projects(st, roster["projects"])
    esc = []
    crash = ""
    pa = st.pop("pass_started", None)
    if pa and pa.get("project") in st["projects"]:
        # The container died mid-pass: count a crash for that project so an
        # OOM-on-A → restart → re-pick-A loop can't starve the rest (blocker §3).
        crash = pa["project"]
        _d, esc = apply_outcome(st["projects"][crash], "crash",
                                roster["cfg"], now)
    cleared = []
    for p in roster["projects"]:
        lock = Path(p["state_dir"]) / "loop.lock"
        if lock.exists():
            # PID namespaces reset on container restart, so a stale pid can
            # false-match a live process and silently skip every pass (§5).
            shutil.rmtree(lock, ignore_errors=True)
            cleared.append(str(lock))
        wins, tz = windows_for(p)
        if wins and seconds_until_open(wins, tz, now) is None:
            print(f"WARN: {p['name']}: roster window ∩ repo schedule.window is "
                  "empty — this project will never run", file=sys.stderr)
    save_state(args.state, st)
    emit(args, {"PROJECTS": " ".join(p["name"] for p in roster["projects"]),
                "CRASH_RECOVERED": crash,
                "LOCKS_CLEARED": " ".join(cleared),
                "ESCALATE_OPS": "; ".join(m for lvl, m in esc if lvl == "ops")})
    return 0


def cmd_pass_start(args):
    roster = load_roster(args.roster)
    st = load_state(args.state)
    ensure_projects(st, roster["projects"])
    now = from_iso(args.now) if args.now else now_utc()
    st["pass_started"] = {"project": args.project, "ts": to_iso(now)}
    save_state(args.state, st)
    return 0


def cmd_status(args):
    roster = load_roster(args.roster)
    st = load_state(args.state)
    ensure_projects(st, roster["projects"])
    now = now_utc()
    pa = st.get("pass_started")
    print(f"orchestrator: {len(roster['projects'])} project(s), "
          f"{'PASS RUNNING: ' + pa['project'] + ' since ' + pa['ts'] if pa else 'between passes'}")
    for p in roster["projects"]:
        ps = st["projects"][p["name"]]
        ne = ps.get("next_eligible")
        due = "now"
        if ne:
            secs = int((from_iso(ne) - now).total_seconds())
            due = f"in {secs // 60}m" if secs > 0 else "now"
        parked = f"  PARKED until {ps['parked_until']}" if ps.get("parked_until") else ""
        print(f"  {p['name']:<20} last={ps.get('last_outcome') or '—':<14} "
              f"next={due:<8} dry={ps['dry_streak']} err={ps['error_streak']} "
              f"crash={ps['crash_streak']}  cadence={p['cadence']}{parked}")
    return 0
```

And register in `main()`:

```python
    p_up = sub.add_parser("startup", help="validate roster, recover write-ahead, clear locks")
    common(p_up)
    p_up.set_defaults(func=cmd_startup)

    p_ps = sub.add_parser("pass-start", help="persist the crash write-ahead record")
    common(p_ps)
    p_ps.add_argument("--project", required=True)
    p_ps.set_defaults(func=cmd_pass_start)

    p_st = sub.add_parser("status", help="human status table")
    common(p_st)
    p_st.set_defaults(func=cmd_status)
```

- [ ] **Step 4: Run tests + full suite**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py && python3 dev-workflow/test_validate.py && python3 skills/ticket-loop/test_telegram.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/orchestrator/orch.py skills/ticket-loop/orchestrator/test_orch.py
git commit -m "feat(orchestrator): startup crash-recovery + boot lock-clear, pass-start write-ahead, status table"
```

---

### Task 5: `queue-count.py` — the tracker queue-depth pre-check (adapter seam)

**Files:**
- Create: `dev-workflow/queue-count.py`
- Test: `dev-workflow/test_queue_count.py`
- Modify: `dev-workflow/tracker-adapters.md` (add the `queue_count` verb row)

**Interfaces:**
- Consumes: `dev-workflow/dw-config.py`'s `_load` + `get` + `_MISSING` (imported by file path from the sibling — works in the repo layout AND the image where both are baked in `/opt/dev-workflow/bin/`).
- Produces:
  - CLI: `LINEAR_API_KEY=… queue-count.py --config <work_tree>/dev-workflow.yml` — prints a bare integer (count of actionable tickets) on stdout, exit 0; ANY failure → non-empty stderr + non-zero exit (the orchestrator fails **open**).
  - Functions (for tests): `read_roles(cfg_data, dwmod) -> (team, label, states, exclude_labels)`, `build_payload(team, label, states) -> dict`, `count_eligible(body, exclude_labels) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `dev-workflow/test_queue_count.py`:

```python
#!/usr/bin/env python3
"""Offline unittests for queue-count.py — query construction + response parsing
only; the single urllib call in main() is never exercised here.

Run: python3 dev-workflow/test_queue_count.py
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("queue_count", HERE / "queue-count.py")
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)


CONFIG = """\
tracker:
  provider: linear
  team: Acme
  roles:
    queue:   { label: agent, states: [Todo, In Progress] }
    blocked: { label: agent-blocked }
    exclude: { labels: [manual, gated] }
    done:    { state: Done }
"""


def load_cfg(text=CONFIG):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "dev-workflow.yml"
        p.write_text(text)
        return qc.load_config(str(p))


class TestReadRoles(unittest.TestCase):
    def test_reads_team_queue_and_excludes(self):
        data, mod = load_cfg()
        team, label, states, excludes = qc.read_roles(data, mod)
        self.assertEqual(team, "Acme")
        self.assertEqual(label, "agent")
        self.assertEqual(states, ["Todo", "In Progress"])
        self.assertEqual(excludes, ["manual", "gated"])

    def test_missing_queue_role_errors(self):
        data, mod = load_cfg("tracker:\n  team: Acme\n")
        with self.assertRaises(SystemExit):
            qc.read_roles(data, mod)

    def test_no_exclude_role_is_empty_list(self):
        data, mod = load_cfg(
            "tracker:\n  team: Acme\n  roles:\n"
            "    queue: { label: agent, states: [Todo] }\n")
        _, _, _, excludes = qc.read_roles(data, mod)
        self.assertEqual(excludes, [])


class TestBuildPayload(unittest.TestCase):
    def test_filter_shape(self):
        payload = qc.build_payload("Acme", "agent", ["Todo", "In Progress"])
        f = payload["variables"]["filter"]
        self.assertEqual(f["team"]["name"]["eq"], "Acme")
        self.assertEqual(f["labels"]["name"]["eq"], "agent")
        self.assertEqual(f["state"]["name"]["in"], ["Todo", "In Progress"])
        self.assertIn("issues(filter: $filter", payload["query"])


class TestCountEligible(unittest.TestCase):
    def body(self, nodes):
        return {"data": {"issues": {"nodes": nodes}}}

    def node(self, key, labels):
        return {"identifier": key,
                "labels": {"nodes": [{"name": n} for n in labels]}}

    def test_counts_and_drops_excluded(self):
        body = self.body([
            self.node("ABC-1", ["agent"]),
            self.node("ABC-2", ["agent", "manual"]),      # excluded
            self.node("ABC-3", ["agent", "Bug"]),
            self.node("ABC-4", ["agent", "GATED"]),       # excluded, case-insensitive
        ])
        self.assertEqual(qc.count_eligible(body, ["manual", "gated"]), 2)

    def test_empty(self):
        self.assertEqual(qc.count_eligible(self.body([]), ["manual"]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 dev-workflow/test_queue_count.py`
Expected: FAIL at import (`queue-count.py` does not exist).

- [ ] **Step 3: Implement**

Create `dev-workflow/queue-count.py`:

```python
#!/usr/bin/env python3
"""Cheap tracker queue-depth pre-check for the ticket-loop orchestrator.

Implements the read-only `queue_count` verb of the tracker-adapter seam for
Linear: count the actionable tickets — queue label + queue states, minus any
exclude label — using the SAME eligibility definition as `list_actionable`
(see tracker-adapters.md; one source of truth, so the pre-check can't silently
drift from what a real pass would pick up).

    LINEAR_API_KEY=lin_api_...  queue-count.py --config <work_tree>/dev-workflow.yml

Prints a bare integer on stdout (exit 0). ANY failure — missing key, bad
config, network error, GraphQL error — exits non-zero with a message on
stderr; the orchestrator treats that as "fail open" and runs the pass.

Stdlib only (urllib). Config parsing is delegated to the sibling dw-config.py
(same directory in both layouts: dev-workflow/ in the repo, /opt/dev-workflow/bin
in the image), so the YAML handling — PyYAML with a stdlib fallback — is never
duplicated.
"""

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

LINEAR_URL = "https://api.linear.app/graphql"

GQL = ("query($filter: IssueFilter) { issues(filter: $filter, first: 100) "
       "{ nodes { identifier labels { nodes { name } } } } }")


def load_config(path):
    """Parse dev-workflow.yml via the sibling dw-config.py; returns (data, module)."""
    dwc = Path(__file__).resolve().parent / "dw-config.py"
    if not dwc.exists():
        sys.exit(f"error: dw-config.py not found next to {__file__}")
    spec = importlib.util.spec_from_file_location("dwconfig", dwc)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        with open(path) as fh:
            return mod._load(fh), mod
    except OSError as exc:
        sys.exit(f"error: cannot read {path}: {exc}")


def read_roles(data, mod):
    """tracker.team + queue role + exclude labels, straight from tracker.roles —
    never hardcoded names (the adapter-seam hard rule)."""
    team = mod.get(data, "tracker.team")
    queue = mod.get(data, "tracker.roles.queue")
    if team is mod._MISSING or queue is mod._MISSING or not isinstance(queue, dict):
        sys.exit("error: tracker.team / tracker.roles.queue missing in config")
    label, states = queue.get("label"), queue.get("states")
    if not label or not isinstance(states, list) or not states:
        sys.exit("error: tracker.roles.queue needs `label` and non-empty `states`")
    exclude = mod.get(data, "tracker.roles.exclude")
    excludes = []
    if isinstance(exclude, dict) and isinstance(exclude.get("labels"), list):
        excludes = [str(x) for x in exclude["labels"]]
    return str(team), str(label), [str(s) for s in states], excludes


def build_payload(team, label, states):
    return {"query": GQL, "variables": {"filter": {
        "team": {"name": {"eq": team}},
        "labels": {"name": {"eq": label}},
        "state": {"name": {"in": states}},
    }}}


def count_eligible(body, exclude_labels):
    """Count nodes carrying none of the exclude labels (client-side filter,
    mirroring the Linear list_actionable mapping)."""
    ex = {e.lower() for e in exclude_labels}
    n = 0
    for node in body["data"]["issues"]["nodes"]:
        names = {l["name"].lower() for l in node["labels"]["nodes"]}
        if names & ex:
            continue
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="path to dev-workflow.yml")
    args = ap.parse_args()
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        sys.exit("error: LINEAR_API_KEY is not set")
    data, mod = load_config(args.config)
    team, label, states, excludes = read_roles(data, mod)
    req = urllib.request.Request(
        LINEAR_URL,
        data=json.dumps(build_payload(team, label, states)).encode(),
        # Personal API keys go bare in Authorization (Bearer is for OAuth tokens).
        headers={"Content-Type": "application/json", "Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        sys.exit(f"error: linear graphql unreachable: {exc}")
    if body.get("errors"):
        sys.exit(f"error: linear: {body['errors'][0].get('message', 'unknown')}")
    print(count_eligible(body, excludes))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 dev-workflow/test_queue_count.py && python3 -m py_compile dev-workflow/queue-count.py && echo OK`
Expected: tests PASS, `OK`.

- [ ] **Step 5: Add the `queue_count` verb to the adapter seam doc**

In `dev-workflow/tracker-adapters.md`, add one row to the **Canonical verbs** table (after the `get_blockers` row):

```markdown
| `queue_count` | `roles.queue` (label + states), `roles.exclude.labels` | Read-only count of `list_actionable`'s result set — the orchestrator's cheap pre-check. MUST share `list_actionable`'s eligibility definition (same roles, same exclude filter) so the pre-check can never silently drift from what a pass would pick up. |
```

And one row to the **Linear mapping** table (after its `get_blockers` row):

```markdown
| `queue_count` | `dev-workflow/queue-count.py` (GraphQL over urllib, keyed by `LINEAR_API_KEY`) | Same filter as `list_actionable` (team + queue label + queue states, exclude labels dropped client-side); returns only the count. Not an MCP call — it must run without a Claude session. |
```

- [ ] **Step 6: Commit**

```bash
git add dev-workflow/queue-count.py dev-workflow/test_queue_count.py dev-workflow/tracker-adapters.md
git commit -m "feat(tracker): queue_count verb — Linear queue-depth pre-check for the orchestrator (one source of truth with list_actionable)"
```

---

### Task 6: `telegram.py peek` — read-only getUpdates (offset never consumed)

**Files:**
- Modify: `skills/ticket-loop/telegram.py` (add `peek` subcommand)
- Test: `skills/ticket-loop/test_telegram.py` (append)

**Interfaces:**
- Consumes: existing `telegram.py` internals (`api`, `load_state`, `require_env`).
- Produces: CLI `telegram.py peek` — prints a bare integer (count of pending human messages in the agent group) and **never** writes `state.json` (offset unchanged). Supervision §7: safe once the orchestrator is the sole consumer per bot; catches a human poke on an idle project.

- [ ] **Step 1: Write the failing tests** (append to `test_telegram.py`, before `__main__`)

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 skills/ticket-loop/test_telegram.py`
Expected: new tests FAIL (`AttributeError: … no attribute 'cmd_peek'`); existing tests still pass.

- [ ] **Step 3: Implement**

In `telegram.py`, add after `cmd_poll`:

```python
def cmd_peek(_args: argparse.Namespace) -> None:
    """Read-only look at pending updates WITHOUT consuming them: getUpdates at the
    stored offset, timeout 0, and NO state write — the offset is untouched, so the
    next real `poll` still sees every message. Prints the count of human messages
    in the agent group. Used by the orchestrator pre-check to catch a human poke
    ("stop", "urgent: X") on an otherwise idle project; safe by construction ONLY
    while a single consumer drives this bot (the orchestrator, after any per-project
    cron is decommissioned)."""
    chat_id = require_env("AGENT_TELEGRAM_CHAT_ID")
    state = load_state()
    updates = api(
        "getUpdates",
        {"offset": state.get("offset", 0), "timeout": 0, "allowed_updates": '["message"]'},
        http_timeout=15,
    )
    count = 0
    for update in updates:
        msg = update.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != chat_id:
            continue
        if (msg.get("from") or {}).get("is_bot"):
            continue
        count += 1
    print(count)
```

Register it in `main()` (after the `poll` parser):

```python
    p_peek = sub.add_parser("peek", help="count pending group messages WITHOUT consuming the offset")
    p_peek.set_defaults(func=cmd_peek)
```

Also add one line to the module docstring's subcommand list (after the `poll` entry):

```
  peek                                Count pending human messages WITHOUT consuming the
                                      getUpdates offset (read-only; the orchestrator pre-check).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 skills/ticket-loop/test_telegram.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/telegram.py skills/ticket-loop/test_telegram.py
git commit -m "feat(telegram): read-only peek subcommand — pre-check poke detection without consuming the offset"
```

---

### Task 7: The pass-outcome contract — SKILL.md section, cron-run.sh stale-file reset, roster example

**Files:**
- Modify: `skills/ticket-loop/SKILL.md`
- Modify: `skills/ticket-loop/cron-run.sh`
- Create: `skills/ticket-loop/orchestrator/roster.example.yml`

**Interfaces:**
- Consumes: the `outcome.json` shape defined in Task 3 (`classify_pass`).
- Produces: the skill instruction that makes every pass write `$TICKET_LOOP_STATE_DIR/outcome.json`; the runner guarantee that a present `outcome.json` always belongs to the current pass.

- [ ] **Step 1: cron-run.sh — delete the stale outcome file before each pass**

In `skills/ticket-loop/cron-run.sh`, directly after the line `mkdir -p "$STATE_DIR" "$LOG_DIR"`, add:

```bash
# Pass-outcome contract: the skill writes <state>/outcome.json as its last act
# (the orchestrator classifies the pass from it — see SKILL.md). Delete any
# stale one here so a crashed/killed pass can never be classified from the
# PREVIOUS pass's line.
rm -f "$STATE_DIR/outcome.json"
```

Verify: `bash -n skills/ticket-loop/cron-run.sh && echo SYNTAX-OK` → `SYNTAX-OK`.

- [ ] **Step 2: SKILL.md — the outcome contract**

In `skills/ticket-loop/SKILL.md`, insert this new section immediately **before** the `## Loop-level failure` section:

```markdown
## Pass outcome line (read by the orchestrator)

**Last act of EVERY pass — even a fully idle one, and also under `--dry-run` /
`--report`:** write a one-line JSON summary to
`$TICKET_LOOP_STATE_DIR/outcome.json` (the runner exports
`TICKET_LOOP_STATE_DIR`; default `.agent-loop/`). The multi-project
orchestrator classifies the pass from this file — productive / dry /
waiting-on-human — to set this project's next wake time. The runner deletes any
stale file before the pass starts, so a missing file makes the pass look idle
and backs the project off: never skip writing it. One shell command:

    printf '{"picked":%d,"pr_opened":%d,"asked":%d,"blocked":%d,"progressed":%s,"error":%s}\n' \
      1 1 0 0 true null > "$TICKET_LOOP_STATE_DIR/outcome.json"

All six keys, every time:

- `picked` — tickets taken into a build this pass (step 5 started).
- `pr_opened` — PRs opened this pass.
- `asked` — clarifying questions / plans sent (step 4's not-confident path).
- `blocked` — tickets given the **blocked** label this pass.
- `progressed` — `true` if any ticket otherwise genuinely advanced: a merge
  closed a ticket (2a), review feedback was addressed (2b), a conflict healed
  (2c), an answer was drained and a ticket unblocked (step 1), a ticket was
  created from a group report. Triage/comment-only advancement counts — this is
  what stops real-but-PR-less work from reading as a dry pass.
- `error` — `null` normally; a short string when the pass aborted on a
  loop-level failure (tracker MCP or Telegram down) — the orchestrator
  escalates it instead of treating the pass as dry.
```

- [ ] **Step 3: roster.example.yml**

Create `skills/ticket-loop/orchestrator/roster.example.yml`:

```yaml
# roster.yml — the orchestrator's project list (the MODE axis: multi-project).
# This file is orchestrator-owned deployment config; each repo's own contract
# stays in its dev-workflow.yml, read per-pass, unchanged. Copy next to your
# volume's work trees (default path: /home/agent/roster.yml) and edit.
#
# Work-tree guard (non-negotiable): every work_tree must live UNDER `root`
# AND contain a `.dw-agent-clone` marker file (touch it when you seed the
# clone). The orchestrator refuses to start otherwise — this is the positive
# allowlist that keeps a live prod checkout from ever being reset --hard.

root: /home/agent            # allowlist root; defaults to this file's directory

# ── cadence axis (roster default; each project may override) ─────────────────
cadence: adaptive            # adaptive = pre-check + backoff ladder; fixed = constant gap
interval: 30m                # the constant gap used where cadence is `fixed`

# ── adaptive tuning (defaults shown; all optional) ────────────────────────────
ladder: [10m, 20m, 40m, 60m] # dry-pass backoff; productive resets to the first rung
waiting_interval: 20m        # waiting-on-human cadence (neither ladder nor fast)
force_full_every: 8h         # unconditional safety pass per project (drift guard)
pass_timeout: 90m            # per-pass process-group timeout → classified error
requeue_delay: 5m            # skipped-lock / low-memory requeue (no ladder advance)
mem_floor_mb: 2560           # skip the turn when host MemAvailable is below this
error_escalate_after: 3      # consecutive error passes before escalating
crash_park_after: 3          # consecutive crashes before parking the project
crash_park_for: 12h

projects:
  - name: niptao
    work_tree: /home/agent/niptao        # dedicated agent clone — NEVER the prod checkout
    env_file: /home/agent/niptao.env     # 600; LINEAR_API_KEY, GH_TOKEN (per-repo
                                         # fine-grained PAT!), TELEGRAM_BOT_TOKEN,
                                         # AGENT_TELEGRAM_CHAT_ID
    state_dir: /home/agent/state/niptao  # state.json, loop.lock, logs, outcome.json
    # model: sonnet                      # optional → TICKET_LOOP_MODEL for the pass
    # tz: Asia/Kolkata                   # optional → TICKET_LOOP_TZ
    # window: "09:00-20:00"              # optional; intersected (tighten-only) with
                                         # the repo's own schedule.window
    # cadence: fixed                     # optional per-project cadence override
    # interval: 45m
```

- [ ] **Step 4: Verify**

Run: `bash -n skills/ticket-loop/cron-run.sh && python3 skills/ticket-loop/test_telegram.py && python3 skills/ticket-loop/orchestrator/test_orch.py`
Expected: all pass. Also sanity-check the example roster parses:

Run: `python3 -c "import yaml; yaml.safe_load(open('skills/ticket-loop/orchestrator/roster.example.yml')); print('YAML OK')"`
Expected: `YAML OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/SKILL.md skills/ticket-loop/cron-run.sh skills/ticket-loop/orchestrator/roster.example.yml
git commit -m "feat(ticket-loop): pass-outcome contract (outcome.json) + stale-file reset + annotated roster example"
```

---

### Task 8: `orchestrator.sh` — the PID-1 driver + offline smoke test

**Files:**
- Create: `skills/ticket-loop/orchestrator/orchestrator.sh`
- Create: `skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh`

**Interfaces:**
- Consumes: `orch.py` subcommands (`startup/next/pass-start/classify/record`, all with `--sh` where noted), `run-pass.sh` (unchanged), `loop-lock.sh status`, `telegram.py` (`questions --json`, `peek`, `send`), `queue-count.py`.
- Produces: the long-lived orchestrator entrypoint. Env contract: `ORCH_ROSTER` (default `/home/agent/roster.yml`), `ORCH_STATE_DIR` (default `<roster dir>/orch`), `ORCH_RUN_PASS` (test override for `run-pass.sh`), `ORCH_MAX_TURNS` (test bound), `ORCH_TELEGRAM_BOT_TOKEN`/`ORCH_TELEGRAM_CHAT_ID` (optional ops channel), forwards `TICKET_LOOP_MCP_CONFIG`/`DW_PLUGIN_DIR` to passes. Control surface: touch-file `<ORCH_STATE_DIR>/run-now` (optionally containing a project name).

- [ ] **Step 1: Write orchestrator.sh**

Create `skills/ticket-loop/orchestrator/orchestrator.sh`:

```bash
#!/bin/bash
# Long-lived round-robin orchestrator over N ticket-loop projects (mode axis:
# multi-project; Approach A). It replaces the SCHEDULER, not the runner: each
# turn shells out to the same run-pass.sh → cron-run.sh → `claude -p
# /ticket-loop` chain the single-project timer shapes use, one pass at a time,
# never two. All scheduling state/math (roster, ladder, windows, write-ahead,
# classification) lives in orch.py next to this script; this file owns process
# concerns: PID-1 signal handling, the per-pass process-group timeout, the
# pre-check commands (which need each project's own secrets), and Telegram
# escalation.
#
# Secret scoping: this process holds NO project secrets. Each pass — and each
# pre-check — runs in a child that sources only that project's env file; the
# orchestrator's own env carries at most the OPS alert channel creds.
#
# stdout is the live dashboard: one decision line per turn (`docker logs -f`).
#
# Env:
#   ORCH_ROSTER              roster.yml           (default /home/agent/roster.yml)
#   ORCH_STATE_DIR           orch state dir       (default <roster dir>/orch)
#   ORCH_RUN_PASS            per-pass runner override (tests; default sibling run-pass.sh)
#   ORCH_MAX_TURNS           exit after N turns   (tests; default: run forever)
#   ORCH_TELEGRAM_BOT_TOKEN / ORCH_TELEGRAM_CHAT_ID   optional ops alert channel
#   TICKET_LOOP_MCP_CONFIG / DW_PLUGIN_DIR / DW_PYTHON  forwarded to each pass when set
#
# Control surface: `touch <ORCH_STATE_DIR>/run-now` (optionally echo a project
# name into it) forces the next turn to run that project, pre-check bypassed.
set -uo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Sibling discovery covers both layouts: repo (orchestrator/ under
# skills/ticket-loop/, queue-count.py in dev-workflow/) and image (flat
# /opt/dev-workflow/bin).
find_sibling() {
  local f
  for f in "$HERE/$1" "$HERE/../$1" "$HERE/../../../dev-workflow/$1"; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}
ORCH_PY="$HERE/orch.py"
RUN_PASS="${ORCH_RUN_PASS:-$(find_sibling run-pass.sh || true)}"
TELEGRAM="$(find_sibling telegram.py || true)"
QUEUE_COUNT="$(find_sibling queue-count.py || true)"
LOCK_SH="$(find_sibling loop-lock.sh || true)"

ROSTER="${ORCH_ROSTER:-/home/agent/roster.yml}"
ORCH_STATE_DIR="${ORCH_STATE_DIR:-$(dirname "$ROSTER")/orch}"
mkdir -p "$ORCH_STATE_DIR"
STATE_FILE="$ORCH_STATE_DIR/orch-state.json"
RUN_NOW_FILE="$ORCH_STATE_DIR/run-now"

# Python runner for orch.py (PEP 723 pyyaml): same dance as cron-run.sh.
if [ -n "${DW_PYTHON:-}" ]; then PY="$DW_PYTHON"
elif command -v uv >/dev/null 2>&1; then PY="uv run --quiet --no-project"
else PY="python3"; fi

ts()  { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { echo "[$(ts)] $*"; }

ops_alert() {
  log "OPS: $*"
  if [ -n "${ORCH_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ORCH_TELEGRAM_CHAT_ID:-}" ] \
     && [ -n "$TELEGRAM" ]; then
    TELEGRAM_BOT_TOKEN="$ORCH_TELEGRAM_BOT_TOKEN" \
    AGENT_TELEGRAM_CHAT_ID="$ORCH_TELEGRAM_CHAT_ID" \
    TICKET_LOOP_STATE_DIR="$ORCH_STATE_DIR" \
      python3 "$TELEGRAM" send "🚨 orchestrator: $*" >/dev/null 2>&1 \
      || log "WARN: ops alert failed to send"
  fi
}

project_alert() {  # $1 env_file, $2 state_dir, $3 message — the project's own bot
  [ -n "$TELEGRAM" ] || return 0
  ( set -a; . "$1"; set +a
    TICKET_LOOP_STATE_DIR="$2" python3 "$TELEGRAM" send "$3" ) >/dev/null 2>&1 \
    || log "WARN: project alert failed to send"
}

# PID-1 discipline (supervision §4): run the container with --init; on SIGTERM
# finish (or timeout-kill) the current pass, persist, exit — never leave a live
# claude mid-ticket. bash runs the trap only between commands, so every wait
# below is chunked ≤5s.
DRAIN=0
trap 'DRAIN=1; log "SIGTERM — draining (current pass finishes or hits its timeout)"' TERM INT

# Run "$@" in its own session/process group; TERM the whole group after $1
# seconds, KILL 30s later (supervision §1 — a wedged MCP must not freeze the fleet).
run_with_timeout() {
  local limit="$1"; shift
  setsid "$@" &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    waited=$((waited + 5))
    if [ "$waited" -ge "$limit" ]; then
      log "pass timeout (${limit}s) — killing process group $pid"
      kill -TERM -- "-$pid" 2>/dev/null
      sleep 30
      kill -KILL -- "-$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
  done
  wait "$pid"
}

sleep_interruptible() {  # wake early on drain or a run-now touch
  local remain="$1" chunk
  while [ "$remain" -gt 0 ]; do
    [ "$DRAIN" = 1 ] && return 0
    [ -f "$RUN_NOW_FILE" ] && return 0
    chunk=$(( remain > 30 ? 30 : remain ))
    sleep "$chunk"
    remain=$(( remain - chunk ))
  done
}

# ── startup: roster validation (marker guard §8), crash write-ahead recovery
#    (§3), lock-clear on boot (§5 — we are PID 1, no pass can be live) ─────────
if ! STARTUP_SH="$($PY "$ORCH_PY" startup --sh --roster "$ROSTER" --state "$STATE_FILE")"; then
  ops_alert "startup failed — roster invalid or work-tree guard tripped; refusing to run"
  sleep 60   # keep `--restart unless-stopped` from hot-looping on a config error
  exit 1
fi
eval "$STARTUP_SH"
[ -n "${CRASH_RECOVERED:-}" ] && log "recovered crash write-ahead: died mid-pass on $CRASH_RECOVERED"
[ -n "${LOCKS_CLEARED:-}" ]   && log "cleared stale lock(s): $LOCKS_CLEARED"
[ -n "${ESCALATE_OPS:-}" ]    && ops_alert "$ESCALATE_OPS"
if [ -z "$RUN_PASS" ]; then
  ops_alert "run-pass.sh not found next to orchestrator.sh — cannot run passes"
  exit 1
fi
log "orchestrator up — roster: ${PROJECTS:-?}"

TURN=0
while :; do
  TURN=$((TURN + 1))
  if [ -n "${ORCH_MAX_TURNS:-}" ] && [ "$TURN" -gt "$ORCH_MAX_TURNS" ]; then
    log "ORCH_MAX_TURNS=$ORCH_MAX_TURNS reached — exiting (test mode)"
    exit 0
  fi
  [ "$DRAIN" = 1 ] && { log "drained — exiting"; exit 0; }

  RUN_NOW_ARGS=()
  if [ -f "$RUN_NOW_FILE" ]; then
    RUN_NOW_ARGS=(--run-now "$(head -1 "$RUN_NOW_FILE" 2>/dev/null | tr -d '[:space:]')")
  fi
  if ! DECISION_SH="$($PY "$ORCH_PY" next --sh --roster "$ROSTER" --state "$STATE_FILE" \
                       ${RUN_NOW_ARGS[@]+"${RUN_NOW_ARGS[@]}"})"; then
    log "WARN: orch.py next failed — retrying in 60s"
    sleep 60
    continue
  fi
  eval "$DECISION_SH"
  [ "${CONSUME_RUN_NOW:-0}" = 1 ] && rm -f "$RUN_NOW_FILE"

  if [ "$ACTION" = "sleep" ]; then
    log "sleep ${SLEEP_S}s — $REASON"
    sleep_interruptible "$SLEEP_S"
    continue
  fi

  # ACTION=run → PROJECT WORK_TREE ENV_FILE STATE_DIR MODEL PROJECT_TZ CADENCE
  #              PRECHECK FORCE_FULL TIMEOUT_S
  record() {  # $1 = outcome class
    local RECORD_SH
    if ! RECORD_SH="$($PY "$ORCH_PY" record --sh --roster "$ROSTER" \
                       --state "$STATE_FILE" --project "$PROJECT" --outcome "$1")"; then
      log "WARN: record failed for $PROJECT ($1)"
      return 1
    fi
    eval "$RECORD_SH"
    log "turn $PROJECT: outcome=$1 next_eligible=${NEXT_ELIGIBLE:-?}"
    [ -n "${ESCALATE_PROJECT:-}" ] && project_alert "$ENV_FILE" "$STATE_DIR" "$ESCALATE_PROJECT"
    [ -n "${ESCALATE_OPS:-}" ] && ops_alert "$PROJECT: $ESCALATE_OPS"
    return 0
  }

  # An interactive `/loop` session holding this project's singleton lock is
  # being actively worked — requeue shortly, never a dry pass (§5).
  if [ -n "$LOCK_SH" ] && TICKET_LOOP_STATE_DIR="$STATE_DIR" bash "$LOCK_SH" status >/dev/null 2>&1; then
    log "$PROJECT: singleton lock held (interactive session?) — requeue"
    record skipped-lock
    continue
  fi

  if [ "${PRECHECK:-0}" = 1 ]; then
    # Cheap pre-check (spec §3): queue depth + open questions + read-only peek.
    # queue-count failures FAIL OPEN (run the pass — it is the source of truth,
    # and a real outage then surfaces as a loud error class, not a silent skip).
    SIGNAL=0 WHY="no work signal"
    QC="$( ( set -a; . "$ENV_FILE"; set +a
             python3 "$QUEUE_COUNT" --config "$WORK_TREE/dev-workflow.yml" ) 2>&1 )"
    case "$QC" in
      0)           : ;;
      ''|*[!0-9]*) SIGNAL=1; WHY="queue-count failed, failing open: ${QC:0:120}" ;;
      *)           SIGNAL=1; WHY="queue depth $QC" ;;
    esac
    if [ "$SIGNAL" = 0 ] && [ -n "$TELEGRAM" ]; then
      QN="$(TICKET_LOOP_STATE_DIR="$STATE_DIR" python3 "$TELEGRAM" questions --json 2>/dev/null \
            | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
      case "$QN" in (*[!0-9]*|'') QN=0 ;; esac
      [ "$QN" -gt 0 ] && { SIGNAL=1; WHY="$QN open question(s) — a human may have answered"; }
    fi
    if [ "$SIGNAL" = 0 ] && [ -n "$TELEGRAM" ]; then
      PK="$( ( set -a; . "$ENV_FILE"; set +a
               TICKET_LOOP_STATE_DIR="$STATE_DIR" python3 "$TELEGRAM" peek ) 2>/dev/null || echo 0 )"
      case "$PK" in (*[!0-9]*|'') PK=0 ;; esac
      [ "$PK" -gt 0 ] && { SIGNAL=1; WHY="$PK unread group message(s)"; }
    fi
    if [ "$SIGNAL" = 0 ]; then
      log "pre-check $PROJECT: idle (queue 0, no questions, no pokes) — skipping pass"
      record precheck-idle
      continue
    fi
    log "pre-check $PROJECT: $WHY — running pass"
  else
    FF_NOTE=""
    [ "${FORCE_FULL:-0}" = 1 ] && FF_NOTE="forced-full, "
    log "pass $PROJECT: no pre-check (${FF_NOTE}cadence=$CADENCE)"
  fi

  # Crash write-ahead BEFORE launch (§3).
  $PY "$ORCH_PY" pass-start --roster "$ROSTER" --state "$STATE_FILE" \
    --project "$PROJECT" >/dev/null 2>&1 \
    || log "WARN: could not persist pass-start write-ahead"

  # Minimal, project-scoped child env (spec §5): the pass sources its own
  # agent.env via DW_ENV_FILE; nothing from any other project leaks in.
  ENV_ARGS=( HOME="$HOME" PATH="$PATH" LANG="${LANG:-C.UTF-8}"
             DW_ENV_FILE="$ENV_FILE" DW_WORK_TREE="$WORK_TREE"
             TICKET_LOOP_STATE_DIR="$STATE_DIR" )
  [ -n "${MODEL:-}" ]                  && ENV_ARGS+=( TICKET_LOOP_MODEL="$MODEL" )
  [ -n "${PROJECT_TZ:-}" ]             && ENV_ARGS+=( TICKET_LOOP_TZ="$PROJECT_TZ" )
  [ -n "${TICKET_LOOP_MCP_CONFIG:-}" ] && ENV_ARGS+=( TICKET_LOOP_MCP_CONFIG="$TICKET_LOOP_MCP_CONFIG" )
  [ -n "${DW_PLUGIN_DIR:-}" ]          && ENV_ARGS+=( DW_PLUGIN_DIR="$DW_PLUGIN_DIR" )

  run_with_timeout "$TIMEOUT_S" env -i "${ENV_ARGS[@]}" "$RUN_PASS"
  RC=$?
  TO_ARGS=()
  [ "$RC" -eq 124 ] && TO_ARGS=(--timed-out)
  CLASSIFY_OUT="$($PY "$ORCH_PY" classify --state-dir "$STATE_DIR" --rc "$RC" \
                   ${TO_ARGS[@]+"${TO_ARGS[@]}"} 2>/dev/null)" \
    || CLASSIFY_OUT="error classify itself failed"
  CLASS="${CLASSIFY_OUT%% *}"
  log "classify $PROJECT: $CLASSIFY_OUT"
  record "$CLASS"
done
```

Run: `bash -n skills/ticket-loop/orchestrator/orchestrator.sh && chmod +x skills/ticket-loop/orchestrator/orchestrator.sh && echo SYNTAX-OK`
Expected: `SYNTAX-OK`.

- [ ] **Step 2: Write the offline smoke test**

Create `skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh`:

```bash
#!/bin/bash
# Offline end-to-end smoke test for orchestrator.sh: one full turn against a
# stub runner — no network, no docker, no claude. Uses fixed cadence so the
# pre-check (which would need Linear/Telegram) is skipped.
#
# Run: bash skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/root/proj" "$TMP/orch"
touch "$TMP/root/proj/.dw-agent-clone"
: > "$TMP/agent.env"

cat > "$TMP/root/roster.yml" <<EOF
root: $TMP/root
cadence: fixed
interval: 30m
projects:
  - name: proj
    work_tree: $TMP/root/proj
    env_file: $TMP/agent.env
    state_dir: $TMP/state
EOF

# Stub runner: pretends one pass opened a PR, via the outcome.json contract.
cat > "$TMP/stub-pass.sh" <<'EOF'
#!/bin/bash
mkdir -p "$TICKET_LOOP_STATE_DIR"
printf '{"picked":1,"pr_opened":1,"asked":0,"blocked":0,"progressed":true,"error":null}\n' \
  > "$TICKET_LOOP_STATE_DIR/outcome.json"
EOF
chmod +x "$TMP/stub-pass.sh"

ORCH_ROSTER="$TMP/root/roster.yml" ORCH_STATE_DIR="$TMP/orch" \
ORCH_RUN_PASS="$TMP/stub-pass.sh" ORCH_MAX_TURNS=1 \
  bash "$HERE/orchestrator.sh"

python3 - "$TMP/orch/orch-state.json" <<'PY'
import json, sys
st = json.load(open(sys.argv[1]))
ps = st["projects"]["proj"]
assert ps["last_outcome"] == "productive", ps
assert ps["next_eligible"], ps
assert "pass_started" not in st, st        # write-ahead consumed by record
print("smoke OK — outcome:", ps["last_outcome"], "next:", ps["next_eligible"])
PY
echo PASS
```

- [ ] **Step 3: Run the smoke test to verify it fails/passes honestly**

Run: `bash skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh`
Expected: log lines (`orchestrator up…`, `pass proj: no pre-check…`, `classify proj: productive…`, `turn proj: outcome=productive…`, `ORCH_MAX_TURNS=1 reached`), then `smoke OK — outcome: productive …` and `PASS`. Debug until it does — this is the one test that exercises the sh↔py seam end to end.

- [ ] **Step 4: Run the full test suite**

Run: `python3 skills/ticket-loop/orchestrator/test_orch.py && python3 skills/ticket-loop/test_telegram.py && python3 dev-workflow/test_queue_count.py && python3 dev-workflow/test_validate.py && bash skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh`
Expected: everything green.

- [ ] **Step 5: Commit**

```bash
git add skills/ticket-loop/orchestrator/orchestrator.sh skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh
git commit -m "feat(orchestrator): PID-1 driver — timeout process-group kill, secret-scoped passes, pre-check, drain, run-now; offline smoke test"
```

---

### Task 9: Packaging + docs — Dockerfile, seed marker, orchestrator README, repo docs

**Files:**
- Modify: `skills/ticket-loop/docker/Dockerfile`
- Modify: `skills/ticket-loop/docker/local-run.sh`
- Create: `skills/ticket-loop/orchestrator/README.md`
- Modify: `skills/ticket-loop/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Dockerfile — bake the orchestrator**

In `skills/ticket-loop/docker/Dockerfile`, extend the existing runner COPY block (the one copying `cron-run.sh` etc. to `/opt/dev-workflow/bin/`) to:

```dockerfile
COPY skills/ticket-loop/cron-run.sh \
     skills/ticket-loop/run-pass.sh \
     skills/ticket-loop/loop-lock.sh \
     skills/ticket-loop/telegram.py \
     skills/ticket-loop/orchestrator/orchestrator.sh \
     skills/ticket-loop/orchestrator/orch.py \
     /opt/dev-workflow/bin/
COPY dev-workflow/dw-config.py dev-workflow/queue-count.py /opt/dev-workflow/bin/
```

And directly above the final `CMD` line, add this comment (CMD itself unchanged — deviation #1 in the header):

```dockerfile
# Default CMD stays the ONE-SHOT pass (the systemd timer shape runs the image
# with no command — swapping this would silently daemonize existing
# deployments). The multi-project orchestrator is started explicitly:
#   docker run … <image> /opt/dev-workflow/bin/orchestrator.sh
```

Verify the paths exist: `ls skills/ticket-loop/orchestrator/orchestrator.sh skills/ticket-loop/orchestrator/orch.py dev-workflow/queue-count.py`.

- [ ] **Step 2: local-run.sh — seed writes the allowlist marker**

In `skills/ticket-loop/docker/local-run.sh` `cmd_seed()`, after the `chown -R 10001:10001` docker run, add:

```bash
  # Orchestrator work-tree guard: mark this clone as orchestrator-ownable
  # (roster entries without this marker are refused at startup).
  docker run --rm -v "$VOLUME":/home/agent "$NODE_IMAGE" \
    bash -lc "touch '/home/agent/$name/.dw-agent-clone' && chown 10001:10001 '/home/agent/$name/.dw-agent-clone'"
```

Verify: `bash -n skills/ticket-loop/docker/local-run.sh`.

- [ ] **Step 3: orchestrator README**

Create `skills/ticket-loop/orchestrator/README.md`:

```markdown
# ticket-loop orchestrator — one box, N projects

CI-for-ticket-work, multiplied: a single long-lived process round-robins N
ticket-loop projects **sequentially** (never two passes at once), each with its
own repo clone, Linear board, Telegram group + bot, and secrets file. It
replaces the *scheduler*, not the *runner* — every turn shells out to the same
`run-pass.sh → cron-run.sh → claude -p /ticket-loop` chain the single-project
shapes use.

Design: `docs/superpowers/specs/2026-07-11-ticket-loop-orchestrator-design.md`.

## The axes (composable, not bundled)

| Axis | This directory provides | The alternative stays first-class |
|---|---|---|
| Mode | **orchestrator** (roster of N) | single-project runner (`install-cron.sh`, `docker/` timer) |
| Cadence | **adaptive** (pre-check + `10m→20m→40m→60m` ladder) | `fixed` (constant interval — set `cadence: fixed`) |
| Packaging | containerized (the existing image + an explicit command) | bare (`orchestrator.sh` under systemd on any host) |
| Host | an always-on box | a laptop |

## How a turn works

```
orch.py next            → run <project>, or sleep to min(next_eligible)
  memory gate           → MemAvailable < 2.5 GiB? skip turn (short requeue)
  window                → roster window ∩ repo schedule.window (skip ≠ ladder)
pre-check (adaptive)    → queue-count.py (Linear depth) + open questions
                          + telegram.py peek (read-only) — all idle? back off
orch.py pass-start      → crash write-ahead
run-pass.sh (timeout,   → the unchanged per-pass runner, child env scoped to
  process-group kill)     ONLY this project's DW_ENV_FILE/WORK_TREE/STATE_DIR
orch.py classify        → productive | dry | waiting | error | skipped-lock
                          (from the skill's outcome.json — see SKILL.md)
orch.py record          → ladder / waiting interval / error streak / park;
                          escalate to the project group + the ops channel
```

Outcome → cadence: **productive** resets to the fast rung; **dry** advances the
ladder (quiet nights back off to the 60m cap on their own — no night mode);
**waiting-on-human** polls at a fixed 20m (polling faster doesn't make humans
answer faster); **error** counts a streak and escalates at 3; a crash-looping
project is parked for 12h after 3 consecutive crashes. A forced full pass runs
every 8h per project regardless of pre-check, so pre-check drift can never
silently starve a board.

## Deployment (docker, the nt shape)

Build the existing image (from the repo root — the Dockerfile already bakes
the orchestrator):

    docker build -f skills/ticket-loop/docker/Dockerfile \
      --build-arg CLAUDE_CODE_VERSION=<pin> -t dw-agent:<pin> .

Volume layout (one mounted volume holds everything writable):

    /home/agent/
      roster.yml            # the roster (start from ../roster.example.yml)
      orch/                 # orchestrator state: orch-state.json, run-now
      <project>/            # dedicated base-branch clone + .dw-agent-clone marker
      <project>.env         # 600 — LINEAR_API_KEY, GH_TOKEN (fine-grained,
                            #   per-repo PAT), TELEGRAM_BOT_TOKEN, chat id
      state/<project>/      # state.json, loop.lock, logs, outcome.json

Seed each work tree as a **dedicated clone** and `touch <tree>/.dw-agent-clone`.
NEVER point a roster entry at a live/prod checkout: every pass runs
`git reset --hard origin/<base>` plus the repo's bootstrap/pre-pass hooks in
that tree. The marker + volume-root allowlist makes the orchestrator refuse
anything else at startup.

Run (all caps non-negotiable on a shared prod box — see the spec's Capacity
section):

    docker run -d --name dw-orchestrator \
      --restart unless-stopped --init \
      --network host \
      --memory=2g --memory-swap=2g --cpus=1 --pids-limit 512 \
      --stop-timeout 5460 \
      --log-opt max-size=10m --log-opt max-file=3 \
      -v dw-agent:/home/agent \
      -e ORCH_TELEGRAM_BOT_TOKEN=<ops bot> -e ORCH_TELEGRAM_CHAT_ID=<ops group> \
      dw-agent:<pin> /opt/dev-workflow/bin/orchestrator.sh

Notes:
- `--init` + the SIGTERM drain: `docker stop` lets the current pass finish or
  hit its timeout — hence the generous `--stop-timeout` (> pass_timeout).
- `--memory-swap` equal to `--memory`: no extra swap beyond RAM.
- The ops channel env vars are the ONLY secrets in the orchestrator's own env;
  per-project secrets live in the per-project env files, sourced by each pass.
- `docker logs -f dw-orchestrator` is the live dashboard (one line per turn).
- Status: `docker exec dw-orchestrator python3 /opt/dev-workflow/bin/orch.py \
    status --roster /home/agent/roster.yml --state /home/agent/orch/orch-state.json`
- Run one project now: `docker exec dw-orchestrator \
    bash -c 'echo <name> > /home/agent/orch/run-now'`

## Onboarding a project (the real critical path)

The loop is tracker-driven; a project can't be round-robined until it has:
1. `dev-workflow.yml` at its repo root (validate: `uv run dev-workflow/validate.py <file>`).
2. A Linear team with the queue/blocked/exclude/done roles mapped in
   `tracker.roles`, and at least one eligible ticket.
3. A Telegram group + a **dedicated** bot (own token + chat id — never share a
   bot across projects: getUpdates offsets contend).
4. An `agent.env` (600) with `LINEAR_API_KEY`, a **fine-grained per-repo**
   `GH_TOKEN`, and the Telegram creds. One PAT across orgs is a prompt-injection
   blast-radius mistake — a malicious ticket on project A must not be able to
   push to project B's org. (Residual risk in the one-container shape: passes
   run as one uid, so B's env file is readable from A's build subagent —
   accepted for single-owner rosters; the isolated-per-container shape is the
   upgrade path.)
5. A dedicated clone on the volume + the `.dw-agent-clone` marker + a roster entry.

## Rollout sequence (nt)

1. Deploy with **niptao only** in the roster; watch several days of decision
   lines (four-class outcomes, ladder behavior, the memory gate under celery
   bursts, the docker-mem sampler).
2. **Decommission niptao's individual cron/launchd job** — two schedulers must
   never drive one project (they fight over the board and the Telegram offset;
   the singleton lock is a safety net, not a license).
3. Add whichever of rasa/paytunes has a board; then the last one. (rasa first
   needs its branch-model decision — single `main` = base = prod, or a `dev` trunk.)
4. Confirm during the watch period whether niptao's runtime `claude -p` shares
   a rate-limit pool with the loop's OAuth token (a dev pass throttling prod
   would show up here).

Deferred by design (rollout-watch items, not day-one): SIGHUP roster reload,
status-dashboard polish, `last-batch.json` crash-replay wiring.
```

- [ ] **Step 4: Pointers in existing docs**

In `skills/ticket-loop/README.md`, add a short section (place it after whatever section describes the containerized/box deployment — read the file and fit the house style):

```markdown
## Multi-project: the orchestrator

One always-on box working N boards under a single round-robin scheduler with
an adaptive pre-check + backoff cadence — `orchestrator/README.md`. Additive:
everything above (interactive `/loop`, the cron/launchd timer, the one-shot
container) stays exactly as documented; fold a project into the orchestrator
and decommission ONLY that project's individual timer.
```

In `CLAUDE.md`:
1. In the Repository Structure tree, under the `skills/` entry, extend the ticket-loop line:

```
│   └── ticket-loop/         # autonomous agent + docker/ runner packaging
│       └── orchestrator/    # multi-project round-robin scheduler (roster.yml,
│                            #   adaptive pre-check + backoff, over the same runner)
```

2. In the tree under `dev-workflow/`, after the `dw-config.py` line, add:

```
│   ├── queue-count.py       # Linear queue-depth pre-check (queue_count verb)
```

3. In the Conventions bullet about `dev-workflow/` Python, extend the final sentence listing tests to also name the new ones:

```
the validator has a `test_validate.py` (`python3 dev-workflow/test_validate.py`);
the orchestrator brain and pre-check have `skills/ticket-loop/orchestrator/test_orch.py`
and `dev-workflow/test_queue_count.py` (same `python3 <file>` idiom)
```

- [ ] **Step 5: Full verification sweep**

```bash
python3 -m py_compile dev-workflow/queue-count.py skills/ticket-loop/orchestrator/orch.py skills/ticket-loop/telegram.py
bash -n skills/ticket-loop/orchestrator/orchestrator.sh skills/ticket-loop/cron-run.sh skills/ticket-loop/docker/local-run.sh
python3 skills/ticket-loop/orchestrator/test_orch.py
python3 skills/ticket-loop/test_telegram.py
python3 dev-workflow/test_queue_count.py
python3 dev-workflow/test_validate.py
bash skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh
```
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add skills/ticket-loop/docker/Dockerfile skills/ticket-loop/docker/local-run.sh \
        skills/ticket-loop/orchestrator/README.md skills/ticket-loop/README.md CLAUDE.md
git commit -m "feat(orchestrator): bake into the agent image, seed marker, deployment + rollout + onboarding docs"
```

---

## Spec-coverage self-check (for the final reviewer)

| Spec item | Where |
|---|---|
| §1 roster.yml (name/work_tree/env_file/state_dir/model/tz/window; roster-level cadence + per-entry override) | Tasks 1–2, roster.example.yml (Task 7) |
| §2 orchestrator loop (long-lived, sequential, PID 1) | Task 8 |
| §3 pre-check: queue depth + open questions (+ peek) | Tasks 5, 6, 8 |
| §4 adaptive backoff, four classes, skill-emitted outcome line | Tasks 3, 7 |
| §5 secret scoping (`env -i`, per-project DW_ENV_FILE only) | Task 8 |
| §6 container packaging (image bake, caps, arm64-compatible base unchanged) | Task 9 |
| §7 singleton lock stays; lock-yield ≠ dry | Tasks 3, 8 |
| §8 marker-file + volume-root allowlist guard | Tasks 1, 4 (startup), 9 (seed) |
| Capacity: MemAvailable headroom gate, hard container limits | Task 2, Task 9 README |
| Supervision 1 per-pass timeout (process group) | Task 8 |
| Supervision 2 error class + streak + ops/project escalation + shared-auth alarm | Task 3 |
| Supervision 3 crash write-ahead + park after k | Tasks 3, 4, 8 |
| Supervision 4 `--init` + SIGTERM drain | Tasks 8, 9 |
| Supervision 5 lock-clear on boot | Task 4 |
| Supervision 6 one-source-of-truth note + forced full pass every 8h | Tasks 5, 2 |
| Supervision 7 getUpdates peek | Task 6 |
| Supervision 8 observability (decision lines, orch-state fields, status, run-now) | Tasks 4, 8 |
| Supervision 9 window intersection, skip ≠ ladder | Task 2 |
| Supervision 10 sleep to min(next_eligible) | Task 2 |
| Onboarding + rollout + decommission caveat + non-deprecation | Task 9 README |
