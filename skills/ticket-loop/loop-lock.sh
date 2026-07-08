#!/bin/bash
# Singleton advisory lock shared by every ticket-loop entrypoint — the always-on
# cron wrapper (cron-run.sh) and an interactive `/loop /ticket-loop` session — so
# only one loop is ever active at a time. Both run on the same machine, so the
# owner's pid is the authority: a live owner wins, a dead owner is reclaimed at
# once, an unreadable one after 2h. Prevents double-drains of the shared Telegram
# offset and double-builds.
#
#   loop-lock.sh acquire <pid> [label]   # exit 0 = acquired, 1 = held by a live owner
#   loop-lock.sh release <pid>           # release only if <pid> is the owner
#   loop-lock.sh status                  # exit 0 + "locked by …", or 1 + "unlocked"
#
# Assumes this script lives at <repo>/.claude/skills/ticket-loop/loop-lock.sh; the
# lock lives at <repo>/.agent-loop/loop.lock alongside the loop's other state.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LOCK="$REPO_ROOT/.agent-loop/loop.lock"
PIDF="$LOCK/pid"; OWNERF="$LOCK/owner"
mkdir -p "$(dirname "$LOCK")"

owner_pid() { cat "$PIDF" 2>/dev/null || true; }

case "${1:-status}" in
  acquire)
    pid="${2:?acquire needs a pid}"; label="${3:-unknown}"
    # Under the cron wrapper the lock is already held on our behalf (the wrapper is
    # our parent). Re-acquiring would race against our own parent and wrongly read
    # as "another loop is running" — so this is a deterministic no-op success.
    if [ -n "${TICKET_LOOP_LOCK_HELD:-}" ]; then
      echo "already held by the cron wrapper (parent) — proceed"; exit 0
    fi
    while :; do
      if mkdir "$LOCK" 2>/dev/null; then
        printf '%s' "$pid" > "$PIDF"; printf '%s' "$label" > "$OWNERF"
        echo "acquired ($label pid $pid)"; exit 0
      fi
      held="$(owner_pid)"
      if [ -n "$held" ] && kill -0 "$held" 2>/dev/null; then
        echo "held by $(cat "$OWNERF" 2>/dev/null || echo '?') pid $held" >&2; exit 1
      fi
      if [ -n "$held" ] || [ -z "$(find "$LOCK" -maxdepth 0 -mmin -120 2>/dev/null)" ]; then
        rm -rf "$LOCK"; continue
      fi
      echo "held by an unreadable owner, not yet stale" >&2; exit 1
    done ;;
  release)
    pid="${2:-}"; held="$(owner_pid)"
    if [ -z "$pid" ] || [ "$held" = "$pid" ]; then
      rm -rf "$LOCK"; echo "released"
    else
      echo "not owner (held by ${held:-none}) — left in place"
    fi
    exit 0 ;;
  status)
    held="$(owner_pid)"
    if [ -n "$held" ] && kill -0 "$held" 2>/dev/null; then
      echo "locked by $(cat "$OWNERF" 2>/dev/null || echo '?') pid $held"; exit 0
    fi
    echo "unlocked"; exit 1 ;;
  *) echo "usage: loop-lock.sh {acquire <pid> [label]|release <pid>|status}" >&2; exit 2 ;;
esac
