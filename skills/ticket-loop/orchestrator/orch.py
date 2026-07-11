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
