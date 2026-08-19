#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Event wake for the ticket-loop orchestrator: long-poll each tenant's Telegram
bot and touch the run-now file the moment a message arrives, so pickup latency
is seconds instead of the polling ladder's minutes.

Design constraints (why this is not a plain poller):

* Telegram allows ONE getUpdates consumer per bot token. The loop's pass is the
  real consumer (telegram.py, offset in the tenant's state.json). This watcher
  therefore NEVER advances the offset — it always long-polls from the loop's own
  confirmed offset, which merely re-confirms what the loop already consumed —
  and it never polls while the tenant's pass may be polling (loop.lock guard,
  plus a short poll timeout so a starting pass never meets a long-hanging call).
* A pending-but-unconsumed update returns IMMEDIATELY on every poll (we never
  ack it), which would busy-loop. After signalling run-now, the watcher waits
  for the loop to consume (offset advanced past what we saw) or a cooldown
  before it polls that bot again.
* Only real messages wake a pass (update carrying `message`/`channel_post`);
  member-joined noise and edits don't burn a claude invocation.

Runs as a child of orchestrator.sh inside the container. Stdlib + PyYAML.
Usage: telegram-wake.py --roster /home/agent/roster.yml \
           --run-now-file /home/agent/orch/run-now [--poll-timeout 20]
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

POLL_TIMEOUT_S = 20        # short so a starting pass never overlaps a long hang
LOCK_RECHECK_S = 10        # sleep while the tenant's pass holds loop.lock
ERROR_BACKOFF_S = 30       # network / 409-conflict backoff
CONSUME_COOLDOWN_S = 600   # re-signal cap if the loop never consumes the update
RUN_NOW_RECHECK_S = 5      # sleep while a run-now signal is already pending

_TOKEN_RE = re.compile(r"^\s*TELEGRAM_BOT_TOKEN\s*=\s*['\"]?([^'\"\s]+)")


def log(msg):
    print(f"[telegram-wake] {msg}", flush=True)


def read_bot_token(env_file):
    """The tenant's dedicated bot token, or None. Never raises."""
    try:
        for line in Path(env_file).read_text().splitlines():
            m = _TOKEN_RE.match(line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return None


def read_offset(state_dir):
    """The loop's confirmed Telegram offset from state.json (0 if unknown)."""
    try:
        st = json.loads((Path(state_dir) / "state.json").read_text())
        return int(st.get("offset") or 0)
    except (OSError, ValueError, TypeError):
        return 0


def wakeworthy(updates):
    """Highest update_id carrying an actual message, else None."""
    best = None
    for u in updates:
        if isinstance(u, dict) and ("message" in u or "channel_post" in u):
            uid = u.get("update_id")
            if isinstance(uid, int) and (best is None or uid > best):
                best = uid
    return best


def get_updates(token, offset, timeout_s):
    """One long poll. Returns a list of updates; raises on transport errors."""
    url = (f"https://api.telegram.org/bot{token}/getUpdates"
           f"?offset={offset + 1}&timeout={timeout_s}")
    with urllib.request.urlopen(url, timeout=timeout_s + 15) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates not ok: {str(data)[:120]}")
    return data.get("result") or []


def signal_run_now(run_now_file, name):
    """Write the tenant name unless a signal is already pending (never clobber
    another tenant's wake — the pending one runs first, ours re-signals after)."""
    p = Path(run_now_file)
    if p.exists():
        return False
    try:
        p.write_text(name + "\n")
        return True
    except OSError:
        return False


def watch(project, run_now_file, poll_timeout, stop):
    name, state_dir = project["name"], project["state_dir"]
    token = project["token"]
    lock = Path(state_dir) / "loop.lock"
    while not stop.is_set():
        if Path(run_now_file).exists():
            stop.wait(RUN_NOW_RECHECK_S); continue
        if lock.exists():                    # pass running: it owns getUpdates
            stop.wait(LOCK_RECHECK_S); continue
        offset = read_offset(state_dir)
        try:
            updates = get_updates(token, offset, poll_timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                RuntimeError, ValueError) as exc:
            log(f"{name}: poll error ({exc}) — backing off {ERROR_BACKOFF_S}s")
            stop.wait(ERROR_BACKOFF_S); continue
        seen = wakeworthy(updates)
        if seen is None:
            continue                          # timeout or noise-only batch
        if signal_run_now(run_now_file, name):
            log(f"{name}: message pending (update {seen}) — run-now signalled")
        # Wait for the loop to consume (offset moves past what we saw) or a
        # cooldown, so an unconsumed update can't busy-loop or re-signal storm.
        deadline = time.monotonic() + CONSUME_COOLDOWN_S
        while not stop.is_set() and time.monotonic() < deadline:
            if read_offset(state_dir) >= seen:
                break
            stop.wait(LOCK_RECHECK_S)


def load_projects(roster_path):
    """Enabled roster projects with a DEDICATED bot token, deduped by token
    (two tenants on one shared bot must not double-poll it — first one wins
    and its wake serves the group)."""
    if yaml is None:
        sys.exit("telegram-wake: PyYAML required (run via uv, or python3-yaml)")
    raw = yaml.safe_load(Path(roster_path).read_text()) or {}
    out, seen_tokens = [], set()
    for entry in raw.get("projects") or []:
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        env_file, state_dir = entry.get("env_file"), entry.get("state_dir")
        if not env_file or not state_dir:
            continue
        token = read_bot_token(env_file)
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        out.append({"name": str(entry["name"]), "state_dir": str(state_dir),
                    "token": token})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", required=True)
    ap.add_argument("--run-now-file", required=True)
    ap.add_argument("--poll-timeout", type=int, default=POLL_TIMEOUT_S)
    args = ap.parse_args(argv)
    projects = load_projects(args.roster)
    if not projects:
        log("no enabled tenants with a bot token — nothing to watch"); return 0
    log("watching: " + " ".join(p["name"] for p in projects))
    stop = threading.Event()
    threads = [threading.Thread(target=watch, daemon=True,
                                args=(p, args.run_now_file, args.poll_timeout,
                                      stop))
               for p in projects]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
