#!/bin/bash
# Install / refresh / uninstall a macOS launchd job that runs the ticket-loop
# headless every 30 min during working hours. (On Linux, adapt to cron or a systemd
# timer that runs the same runner.) Idempotent. Two shapes:
#
#   LEGACY (in-tree) — the LaunchAgent runs the WORK TREE's own cron-run.sh, so the
#   runner is part of the checkout it drives (a reset self-updates it):
#     TICKET_LOOP_WORKTREE=/path/to/worktree install-cron.sh              # (re)load
#     TICKET_LOOP_WORKTREE=/path/to/worktree install-cron.sh --refresh    # pull → origin/dev
#
#   EXTERNAL (framework) — the LaunchAgent runs the FRAMEWORK's run-pass.sh against a
#   SEPARATE target checkout, mirroring the container's boundary rule 2 on bare macOS.
#   The runner lives outside the work tree it drives (the read-only-runner property):
#     install-cron.sh --work-tree ~/repos/your-repo --env-file ~/.config/dev-workflow/agent.env
#     install-cron.sh --work-tree ~/repos/your-repo --env-file ... --opt --mcp-keyed
#
#     --work-tree <path>  the TARGET repo checkout (must be a git repo with
#                         dev-workflow.yml at its root). Or set DW_WORK_TREE.
#     --env-file  <path>  an agent.env-style secrets file run-pass.sh sources
#                         (LINEAR_API_KEY, TELEGRAM_BOT_TOKEN, AGENT_TELEGRAM_CHAT_ID,
#                         GH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN). Or set DW_ENV_FILE.
#     --opt               first copy the runner + plugin root-owned to /opt/dev-workflow
#                         via sudo (755, mirrors the image layout), then point the plist
#                         there. The hardened form: the agent's account can't edit its
#                         own leash. Without it, the plist points at this clone's copies.
#     --mcp-keyed         use the keyed tracker MCP (loop-mcp.json) so Linear needs no
#                         browser OAuth — for headless machines with a static
#                         LINEAR_API_KEY in the env file. Requires --env-file.
#
#   install-cron.sh --uninstall                                          # boot out + remove
#
# The daily digest is NOT a separate job — the skill emits it on the first pass of
# each day, so whenever the machine first wakes into the window that pass sends it.
# StartCalendarInterval fires in the machine's LOCAL timezone; set TICKET_LOOP_TZ so
# the loop's "new day" follows a chosen zone (threaded into the plist in external mode;
# TICKET_LOOP_MODEL is too, else build.model from dev-workflow.yml is the fallback the
# runner already reads).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # framework repo root (has .claude-plugin/ + skills/)

LABEL="${TICKET_LOOP_LABEL:-com.example.ticket-loop}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

LOOP_WORKTREE="${TICKET_LOOP_WORKTREE:-}"   # legacy in-tree layout
WORK_TREE="${DW_WORK_TREE:-}"               # external-runner target repo
ENV_FILE="${DW_ENV_FILE:-}"
USE_OPT=0
MCP_KEYED=0
ACTION=install

while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall|uninstall) ACTION=uninstall ;;
    --refresh|refresh)     ACTION=refresh ;;
    --work-tree) shift; WORK_TREE="${1:-}"; [ -n "$WORK_TREE" ] || { echo "ERROR: --work-tree needs a path" >&2; exit 2; } ;;
    --env-file)  shift; ENV_FILE="${1:-}";  [ -n "$ENV_FILE" ]  || { echo "ERROR: --env-file needs a path"  >&2; exit 2; } ;;
    --opt)       USE_OPT=1 ;;
    --mcp-keyed) MCP_KEYED=1 ;;
    install|"")  : ;;
    *) echo "usage: install-cron.sh [--work-tree <path>] [--env-file <path>] [--opt] [--mcp-keyed] [--refresh|--uninstall]" >&2; exit 2 ;;
  esac
  shift
done

uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Uninstalled $LABEL (booted out, plist removed). The work tree is left in place."
}

# StartCalendarInterval entries: every 30 min, 09:00–20:00 inclusive.
build_intervals() {
  local h m out=""
  for h in $(seq 9 19); do
    for m in 0 30; do
      out="$out
    <dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>$m</integer></dict>"
    done
  done
  out="$out
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>"
  printf '%s' "$out"
}

case "$ACTION" in
  uninstall) uninstall; exit 0 ;;
  refresh)
    TARGET="${WORK_TREE:-$LOOP_WORKTREE}"
    : "${TARGET:?set TICKET_LOOP_WORKTREE (or --work-tree) to the checkout to refresh}"
    git -C "$TARGET" fetch --quiet origin dev
    git -C "$TARGET" reset --hard origin/dev
    echo "Refreshed $TARGET → origin/dev"; exit 0 ;;
esac

intervals="$(build_intervals)"

install_and_load() {  # install_and_load <program-arg-runner> <env-xml-or-empty> <launchd-log>
  local runner="$1" envxml="$2" log="$3" envblock=""
  [ -n "$envxml" ] && envblock="  <key>EnvironmentVariables</key>
  <dict>
$envxml
  </dict>
"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$runner</string>
  </array>
$envblock  <key>StartCalendarInterval</key>
  <array>$intervals
  </array>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  launchctl enable "$DOMAIN/$LABEL"
}

# ── legacy in-tree mode: the plist runs the work tree's OWN cron-run.sh, no env block ──
if [ -z "$WORK_TREE" ]; then
  : "${LOOP_WORKTREE:?set TICKET_LOOP_WORKTREE=/path/to/a/dedicated/worktree (or use --work-tree)}"
  WRAPPER="$LOOP_WORKTREE/.claude/skills/ticket-loop/cron-run.sh"
  [ -x "$WRAPPER" ] || { echo "ERROR: wrapper not found/executable: $WRAPPER" >&2; exit 1; }
  mkdir -p "$LOOP_WORKTREE/.agent-loop/logs"
  install_and_load "$WRAPPER" "" "$LOOP_WORKTREE/.agent-loop/logs/ticket-loop-launchd.log"
  echo "Installed $LABEL (in-tree)"
  echo "  schedule : every 30 min, 09:00–20:00 local (digest on the day's first pass)"
  echo "  wrapper  : $WRAPPER"
  echo "  plist    : $PLIST"
  echo "  logs     : $LOOP_WORKTREE/.agent-loop/logs/ticket-loop-cron.log"
  exit 0
fi

# ── external (framework) mode ──────────────────────────────────────────────────
# Guard rails: the work tree must be a real git repo carrying dev-workflow.yml.
git -C "$WORK_TREE" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "ERROR: --work-tree is not a git repo: $WORK_TREE" >&2; exit 1; }
WORK_TREE="$(cd "$WORK_TREE" && pwd)"
[ -f "$WORK_TREE/dev-workflow.yml" ] || {
  echo "ERROR: no dev-workflow.yml at the work-tree root: $WORK_TREE/dev-workflow.yml" >&2
  echo "       the runner reads it for base branch, model, timezone, and state dir." >&2
  exit 1
}

if [ "$MCP_KEYED" = "1" ] && [ -z "$ENV_FILE" ]; then
  echo "ERROR: --mcp-keyed needs --env-file (the keyed MCP reads LINEAR_API_KEY from it)" >&2
  exit 1
fi
if [ "$USE_OPT" = "1" ] && ! command -v sudo >/dev/null 2>&1; then
  echo "ERROR: --opt needs sudo to write /opt/dev-workflow, but sudo was not found" >&2
  exit 1
fi

# Secrets file: warn (never fail, never print its contents) if missing or lax.
if [ -n "$ENV_FILE" ]; then
  if [ ! -f "$ENV_FILE" ]; then
    echo "WARN: env file not found: $ENV_FILE — run-pass.sh will warn; secrets may be missing" >&2
  else
    mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || echo '')"
    [ "$mode" = "600" ] || echo "WARN: env file $ENV_FILE is mode ${mode:-unknown}, expected 600 — chmod 600 it (it holds secrets)" >&2
  fi
fi

# Where the plist points: /opt (hardened, root-owned) or this framework clone.
if [ "$USE_OPT" = "1" ]; then
  OPT_ROOT=/opt/dev-workflow
  echo "Copying runner + plugin to $OPT_ROOT (sudo, root-owned 755)…"
  sudo rm -rf "$OPT_ROOT"
  sudo mkdir -p "$OPT_ROOT/bin" "$OPT_ROOT/plugin"
  sudo cp "$SCRIPT_DIR/run-pass.sh" "$SCRIPT_DIR/cron-run.sh" \
          "$SCRIPT_DIR/loop-lock.sh" "$SCRIPT_DIR/telegram.py" "$OPT_ROOT/bin/"
  sudo cp "$FW_ROOT/dev-workflow/dw-config.py" "$OPT_ROOT/bin/"
  sudo cp -R "$FW_ROOT/.claude-plugin" "$OPT_ROOT/plugin/.claude-plugin"
  sudo cp -R "$FW_ROOT/skills" "$OPT_ROOT/plugin/skills"
  sudo cp "$SCRIPT_DIR/docker/loop-mcp.json" "$OPT_ROOT/loop-mcp.json"
  sudo chown -R root:wheel "$OPT_ROOT"
  sudo chmod -R 755 "$OPT_ROOT"
  RUN_PASS="$OPT_ROOT/bin/run-pass.sh"
  PLUGIN_DIR="$OPT_ROOT/plugin"
  MCP_CONFIG="$OPT_ROOT/loop-mcp.json"
else
  RUN_PASS="$SCRIPT_DIR/run-pass.sh"
  PLUGIN_DIR="$FW_ROOT"
  MCP_CONFIG="$SCRIPT_DIR/docker/loop-mcp.json"
fi
[ -x "$RUN_PASS" ] || { echo "ERROR: runner not found/executable: $RUN_PASS" >&2; exit 1; }

# State + logs follow TICKET_LOOP_STATE_DIR (default <work-tree>/.agent-loop).
STATE_DIR_REL="${TICKET_LOOP_STATE_DIR:-.agent-loop}"
case "$STATE_DIR_REL" in
  /*) STATE_DIR="$STATE_DIR_REL" ;;
  *)  STATE_DIR="$WORK_TREE/$STATE_DIR_REL" ;;
esac
mkdir -p "$STATE_DIR/logs"
LAUNCHD_LOG="$STATE_DIR/logs/ticket-loop-launchd.log"

# Plist EnvironmentVariables: DW_* wire the runner; the TICKET_LOOP_* knobs are only
# threaded when set (else the runner's own dev-workflow.yml defaults apply).
kv() { printf '    <key>%s</key><string>%s</string>' "$1" "$2"; }
ENVXML="$(kv DW_WORK_TREE "$WORK_TREE")
$(kv DW_PLUGIN_DIR "$PLUGIN_DIR")"
if [ -n "$ENV_FILE" ]; then ENVXML="$ENVXML
$(kv DW_ENV_FILE "$ENV_FILE")"; fi
if [ "$MCP_KEYED" = "1" ]; then ENVXML="$ENVXML
$(kv TICKET_LOOP_MCP_CONFIG "$MCP_CONFIG")"; fi
if [ -n "${TICKET_LOOP_STATE_DIR:-}" ]; then ENVXML="$ENVXML
$(kv TICKET_LOOP_STATE_DIR "$TICKET_LOOP_STATE_DIR")"; fi
if [ -n "${TICKET_LOOP_TZ:-}" ]; then ENVXML="$ENVXML
$(kv TICKET_LOOP_TZ "$TICKET_LOOP_TZ")"; fi
if [ -n "${TICKET_LOOP_MODEL:-}" ]; then ENVXML="$ENVXML
$(kv TICKET_LOOP_MODEL "$TICKET_LOOP_MODEL")"; fi

install_and_load "$RUN_PASS" "$ENVXML" "$LAUNCHD_LOG"

echo "Installed $LABEL (external$([ "$USE_OPT" = "1" ] && echo ', /opt hardened' || echo ', clone'))"
echo "  schedule  : every 30 min, 09:00–20:00 local (digest on the day's first pass)"
echo "  runner    : $RUN_PASS"
echo "  work tree : $WORK_TREE"
echo "  plugin    : $PLUGIN_DIR"
[ -n "$ENV_FILE" ] && echo "  env file  : $ENV_FILE (secrets — sourced by run-pass.sh, never printed)"
[ "$MCP_KEYED" = "1" ] && echo "  mcp       : keyed ($MCP_CONFIG)"
echo "  plist     : $PLIST"
echo "  logs      : $STATE_DIR/logs/ticket-loop-cron.log"
