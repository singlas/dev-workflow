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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
