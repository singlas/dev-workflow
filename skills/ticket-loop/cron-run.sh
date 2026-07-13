#!/bin/bash
# Headless single-pass runner for the ticket-loop, driven by an always-on scheduler
# (macOS launchd / Linux cron / systemd timer). Runs ONE `/ticket-loop` pass while
# holding the shared singleton lock (loop-lock.sh) so it never overlaps another tick
# OR an interactive `/loop /ticket-loop` session. Extra args pass through to the
# skill (e.g. --report, --dry-run).
#
# This runner is codebase-agnostic. It works in TWO layouts:
#   • laptop (legacy)  — copied into the target repo at
#       <repo>/.claude/skills/ticket-loop/cron-run.sh; the runner IS part of the
#       work tree, so a reset to origin/<base> self-updates it.
#   • container        — baked root-owned at /opt/dev-workflow/bin/cron-run.sh
#       (boundary rule 2); the target checkout is the mounted volume, and the
#       systemd unit sets DW_WORK_TREE. The runner is external and never self-updates
#       (its version == the image version); only a rebuild changes how the loop runs.
#
# Per-repo config lives at $DW_WORK_TREE/dev-workflow.yml (model, base branch, tz,
# state dir, pre-pass hook). Read via dw-config.py; every value degrades to a sane
# default when the file (or dw-config.py) is absent, so a bare laptop copy still runs.
#
# A scheduler hands us almost no environment, so we set PATH/locale explicitly. TZ
# matters: the digest's "new day" trigger depends on it — set TICKET_LOOP_TZ (or
# schedule.tz in the config) to your team's timezone.
set -uo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

# ── layout awareness ──
# DW_ROOT is where this script + its siblings (loop-lock.sh, telegram.py, and — in
# the image — dw-config.py) live. DW_WORK_TREE is the target-repo checkout to drive.
DW_ROOT="${DW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
if [ -z "${DW_WORK_TREE:-}" ]; then
  # legacy laptop layout: runner sits at <repo>/.claude/skills/ticket-loop, so the
  # repo root is three levels up.
  DW_WORK_TREE="$(cd "$DW_ROOT/../../.." && pwd)"
fi

# Is the runner physically inside the work tree (laptop) or external (container)?
RUNNER_INSIDE_WORKTREE=0
case "$DW_ROOT/" in
  "$DW_WORK_TREE"/*) RUNNER_INSIDE_WORKTREE=1 ;;
esac

# ── per-repo config reader (dev-workflow.yml + dw-config.py) ──
CFG="$DW_WORK_TREE/dev-workflow.yml"
DWCONFIG_PY=""
for _c in "$DW_ROOT/dw-config.py" "$DW_WORK_TREE/dev-workflow/dw-config.py"; do
  [ -f "$_c" ] && { DWCONFIG_PY="$_c"; break; }
done
# Preferred runner: `uv run` — dw-config.py carries PEP 723 metadata, so uv supplies
# PyYAML from its cache (no venv, no project sync). Fallbacks: DW_PYTHON, then a bare
# python3 — dw-config.py has a stdlib-only YAML fallback, so it reads the config even
# where PyYAML is absent (macOS ships a bare 3.x).
DW_RUN=""
if [ -n "${DW_PYTHON:-}" ]; then
  DW_RUN="$DW_PYTHON"
elif command -v uv >/dev/null 2>&1; then
  DW_RUN="uv run --quiet --no-project"
elif command -v python3 >/dev/null 2>&1; then
  DW_RUN="python3"
fi
if [ -z "$DW_RUN" ] && [ -f "$CFG" ]; then
  echo "WARN: no uv or python3 found — dev-workflow.yml values fall back to defaults; install uv or python3, or set DW_PYTHON" >&2
fi
# cfg <dotted.path> [default] — prints the config value, else the default, else fails.
cfg() {
  if [ -f "$CFG" ] && [ -n "$DWCONFIG_PY" ] && [ -n "$DW_RUN" ]; then
    $DW_RUN "$DWCONFIG_PY" "$CFG" "$@" 2>/dev/null && return 0
  fi
  if [ "$#" -ge 2 ]; then printf '%s\n' "$2"; return 0; fi
  return 1
}

BASE_BRANCH="$(cfg repo.base_branch dev)"

# TZ: env override wins, else schedule.tz, else the system zone.
if [ -n "${TICKET_LOOP_TZ:-}" ]; then
  export TZ="$TICKET_LOOP_TZ"
elif _tz="$(cfg schedule.tz 2>/dev/null)" && [ -n "$_tz" ]; then
  export TZ="$_tz"
fi

# State + logs live under the state dir (env override, else runtime.state_dir, else
# .agent-loop), resolved absolute and exported so loop-lock.sh + telegram.py agree.
STATE_DIR_REL="${TICKET_LOOP_STATE_DIR:-$(cfg runtime.state_dir .agent-loop)}"
case "$STATE_DIR_REL" in
  /*) STATE_DIR="$STATE_DIR_REL" ;;
  *)  STATE_DIR="$DW_WORK_TREE/$STATE_DIR_REL" ;;
esac
export TICKET_LOOP_STATE_DIR="$STATE_DIR"
LOG_DIR="$STATE_DIR/logs"
LOG="$LOG_DIR/ticket-loop-cron.log"
LOCKER="$DW_ROOT/loop-lock.sh"
mkdir -p "$STATE_DIR" "$LOG_DIR"
# Pass-outcome contract: the skill writes <state>/outcome.json as its last act
# (the orchestrator classifies the pass from it — see SKILL.md). Delete any
# stale one here so a crashed/killed pass can never be classified from the
# PREVIOUS pass's line.
rm -f "$STATE_DIR/outcome.json"

ts()  { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# rotate a single generation at ~5 MB (claude -p prints only its final result, so
# this rarely trips).
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
  mv -f "$LOG" "$LOG.1"
fi

# ── singleton lock: yield if any loop (cron or interactive) is already live ──
if ! acq="$(bash "$LOCKER" acquire "$$" cron 2>&1)"; then
  log "skip: $acq"
  exit 0
fi
trap 'bash "$LOCKER" release "$$" >/dev/null 2>&1' EXIT
# tell the skill the wrapper already holds the singleton lock, so its own
# Preconditions don't try (and fail) to re-acquire it under us.
export TICKET_LOOP_LOCK_HELD=1

cd "$DW_WORK_TREE" || { log "FATAL: work tree $DW_WORK_TREE missing"; exit 1; }

# ── keep the work tree current with origin/<base> ──
# Nothing else edits this tree (the loop's build subagents make their own
# worktrees), so a hard reset is safe — EXCEPT in manager/parent mode, where the
# work tree is a parent checkout holding child clones + docs + PM state and must
# never be reset (child clones are reset per-child by the parent skill).
MANAGER="${DW_MANAGER:-$(cfg agent.manager false 2>/dev/null || echo false)}"
# lowercase first: dw-config prints a YAML boolean as Python True/False (capital).
case "$(printf '%s' "$MANAGER" | tr 'A-Z' 'a-z')" in 1|true|yes|on) MANAGER=1 ;; *) MANAGER=0 ;; esac
if [ "$MANAGER" = 1 ]; then
  log "manager mode — parent work tree, skipping git reset"
elif [ "$RUNNER_INSIDE_WORKTREE" = "1" ]; then
  # Laptop layout: the runner IS part of the work tree, so the reset self-updates it.
  # Guard: only reset once origin/<base> actually carries this wrapper, so a
  # pre-merge window (scripts still on the feature branch) doesn't wipe them.
  if git fetch --quiet origin "$BASE_BRANCH" 2>>"$LOG"; then
    if ! git diff --quiet HEAD 2>/dev/null; then
      log "note: work tree has local changes — skipping reset, running as-is"
    elif git cat-file -e "origin/$BASE_BRANCH:.claude/skills/ticket-loop/cron-run.sh" 2>/dev/null; then
      git reset --hard --quiet "origin/$BASE_BRANCH" 2>>"$LOG" || log "WARN: git reset failed"
    else
      log "note: origin/$BASE_BRANCH has no cron-run.sh yet (pre-merge) — running current checkout"
    fi
  else
    log "WARN: git fetch failed — running current checkout"
  fi
else
  # Container layout: the runner is external (/opt/dev-workflow) and version-pinned
  # to the image, so NO self-update — but still keep the work tree current.
  if git fetch --quiet origin "$BASE_BRANCH" 2>>"$LOG"; then
    git reset --hard --quiet "origin/$BASE_BRANCH" 2>>"$LOG" || log "WARN: git reset failed"
  else
    log "WARN: git fetch failed — running current checkout"
  fi
fi

# ── pre-pass hook (replaces the old hardcoded worktree prune) ──
# If the repo config defines hooks.pre_pass, run it under the held lock, cwd = work
# tree, before invoking claude (e.g. refresh a board snapshot, prune stale worktrees).
PRE_PASS="$(cfg hooks.pre_pass '' 2>/dev/null || true)"
if [ -n "$PRE_PASS" ]; then
  log "pre_pass: $PRE_PASS"
  ( cd "$DW_WORK_TREE" && bash -c "$PRE_PASS" ) >>"$LOG" 2>&1 || log "WARN: pre_pass hook failed"
fi

# ── run one headless pass ──
# --dangerously-skip-permissions is required for unattended headless operation (no
# human to approve tool calls). The loop's own guardrails (scoped edits, no secret
# reads, isolated-worktree subagents) live in the ticket-loop SKILL.
#
# --model: pin the tier explicitly when set (env override, else build.model from the
# config) so the loop and the build subagents it spawns don't drift with a local
# /model change. Omitted entirely when neither is set.
MODEL="${TICKET_LOOP_MODEL:-}"
if [ -z "$MODEL" ]; then MODEL="$(cfg build.model '' 2>/dev/null || true)"; fi
MODEL_ARGS=()
[ -n "$MODEL" ] && MODEL_ARGS=(--model "$MODEL")

# Optional keyed MCP config (the box/container path): when TICKET_LOOP_MCP_CONFIG
# points at a config that carries the tracker's `Authorization: Bearer <key>`
# header, pass it with --strict-mcp-config so the loop uses ONLY that (a static API
# key, no interactive OAuth) instead of the repo's OAuth-based .mcp.json. Unset on
# the laptop → the repo .mcp.json (interactive OAuth) is used, unchanged.
MCP_ARGS=()
if [ -n "${TICKET_LOOP_MCP_CONFIG:-}" ]; then
  MCP_ARGS=(--mcp-config "$TICKET_LOOP_MCP_CONFIG" --strict-mcp-config)
fi

# Skill invocation: repo-local `/ticket-loop` by default. When DW_PLUGIN_DIR is set
# AND the pinned claude supports --plugin-dir, load the baked plugin and invoke the
# namespaced skill instead.
# Which skill: DW_SKILL_INVOCATION (a full invoke string) is the ultimate
# override; else a bare skill NAME from DW_SKILL (roster `skill:`) or the repo's
# agent.skill, defaulting to ticket-loop. The runner namespaces the name.
SKILL_NAME="${DW_SKILL:-$(cfg agent.skill ticket-loop 2>/dev/null || echo ticket-loop)}"
[ -n "$SKILL_NAME" ] || SKILL_NAME="ticket-loop"
INVOKE="${DW_SKILL_INVOCATION:-/$SKILL_NAME}"
PLUGIN_ARGS=()
if [ -n "${DW_PLUGIN_DIR:-}" ]; then
  if claude --help 2>/dev/null | grep -q -- --plugin-dir; then
    PLUGIN_ARGS=(--plugin-dir "$DW_PLUGIN_DIR")
    INVOKE="${DW_SKILL_INVOCATION:-/dev-workflow:$SKILL_NAME}"
  else
    log "WARN: pinned claude lacks --plugin-dir; falling back to repo-local /$SKILL_NAME"
  fi
fi

log "=== $INVOKE $* — start (HEAD $(git rev-parse --short HEAD 2>/dev/null)${MODEL:+, model $MODEL}) ==="
claude -p "$INVOKE $*" \
  ${MODEL_ARGS[@]+"${MODEL_ARGS[@]}"} \
  ${MCP_ARGS[@]+"${MCP_ARGS[@]}"} \
  ${PLUGIN_ARGS[@]+"${PLUGIN_ARGS[@]}"} \
  --dangerously-skip-permissions >> "$LOG" 2>&1
rc=$?
# Regression guard: a headless -p pass must run its build subagents in the
# FOREGROUND (see the ticket-loop SKILL). If the pass ever backgrounds one, the
# print harness kills it at the background-wait ceiling and prints this line — a
# build was silently guillotined mid-flight (0 commits, no PR). Surface it loudly
# instead of letting the pass look clean; the exit code stays 0 in that case.
if tail -n 40 "$LOG" | grep -q "Background tasks still running"; then
  log "WARN: pass terminated background task(s) at the -p ceiling — a build was likely killed mid-flight (SKILL rule: builds must run foreground, run_in_background:false)."
fi
log "=== $INVOKE $* — done (exit $rc) ==="
exit "$rc"
