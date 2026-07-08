#!/bin/bash
# Headless single-pass runner for the ticket-loop, for an always-on scheduler
# (macOS launchd / Linux cron / systemd timer). Runs ONE `/ticket-loop` pass while
# holding the shared singleton lock (loop-lock.sh) so it never overlaps another
# tick OR an interactive `/loop /ticket-loop` session. Extra args pass through to
# the skill (e.g. --report, --dry-run).
#
# Assumes it lives at <repo>/.claude/skills/ticket-loop/cron-run.sh and that <repo>
# is a dedicated worktree the loop "sits" in (its build subagents make their own
# isolated worktrees). Set TICKET_LOOP_TZ to your team's timezone so the digest's
# "new day" trigger is correct.
set -uo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
[ -n "${TICKET_LOOP_TZ:-}" ] && export TZ="$TICKET_LOOP_TZ"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

WORKTREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SKILL_DIR="$WORKTREE/.claude/skills/ticket-loop"
LOG_DIR="$WORKTREE/.agent-loop/logs"
LOG="$LOG_DIR/ticket-loop-cron.log"
LOCKER="$SKILL_DIR/loop-lock.sh"
mkdir -p "$WORKTREE/.agent-loop" "$LOG_DIR"

ts()  { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# rotate a single generation at ~5 MB (claude -p prints only its final result).
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
  mv -f "$LOG" "$LOG.1"
fi

# ── singleton lock: yield if any loop (cron or interactive) is already live ──
if ! acq="$(bash "$LOCKER" acquire "$$" cron 2>&1)"; then
  log "skip: $acq"
  exit 0
fi
trap 'bash "$LOCKER" release "$$" >/dev/null 2>&1' EXIT
export TICKET_LOOP_LOCK_HELD=1   # tells the skill the wrapper already holds the lock

cd "$WORKTREE" || { log "FATAL: worktree $WORKTREE missing"; exit 1; }

# ── keep the sitting worktree current with origin/dev ──
# Nothing else edits this tree, so a hard reset is safe — but skip it when the tree
# is dirty, or before the scripts have landed on origin/dev (guards a pre-merge
# rollout from wiping the not-yet-merged wrapper).
if git fetch --quiet origin dev 2>>"$LOG"; then
  if ! git diff --quiet HEAD 2>/dev/null; then
    log "note: worktree has local changes — skipping reset, running as-is"
  elif git cat-file -e origin/dev:.claude/skills/ticket-loop/cron-run.sh 2>/dev/null; then
    git reset --hard --quiet origin/dev 2>>"$LOG" || log "WARN: git reset failed"
  else
    log "note: origin/dev has no cron-run.sh yet (pre-merge) — running current checkout"
  fi
else
  log "WARN: git fetch failed — running current checkout"
fi

# ── run one headless pass ──
# --dangerously-skip-permissions is required for unattended headless operation (no
# human to approve tool calls). The loop's own guardrails (scoped edits, no secret
# reads, isolated-worktree subagents) live in the ticket-loop SKILL.
log "=== /ticket-loop $* — start (HEAD $(git rev-parse --short HEAD 2>/dev/null)) ==="
claude -p "/ticket-loop $*" --dangerously-skip-permissions >> "$LOG" 2>&1
rc=$?
log "=== /ticket-loop $* — done (exit $rc) ==="
exit "$rc"
