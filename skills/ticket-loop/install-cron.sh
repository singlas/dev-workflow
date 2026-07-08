#!/bin/bash
# Install / refresh / uninstall a macOS launchd job that runs the ticket-loop
# headless every 30 min during working hours. (On Linux, adapt to cron or a systemd
# timer that runs the same cron-run.sh.) Idempotent.
#
#   TICKET_LOOP_WORKTREE=/path/to/worktree install-cron.sh              # (re)load
#   TICKET_LOOP_WORKTREE=/path/to/worktree install-cron.sh --refresh    # pull → origin/dev
#   install-cron.sh --uninstall                                         # boot out + remove
#
# The daily digest is NOT a separate job — the skill emits it on the first pass of
# each day, so whenever the machine first wakes into the window that pass sends it.
# StartCalendarInterval fires in the machine's LOCAL timezone; set TICKET_LOOP_TZ in
# the plist env if the loop's "new day" should follow a different zone.
set -euo pipefail

LABEL="${TICKET_LOOP_LABEL:-com.example.ticket-loop}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOOP_WORKTREE="${TICKET_LOOP_WORKTREE:-}"
DOMAIN="gui/$(id -u)"

uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Uninstalled $LABEL (booted out, plist removed). The worktree is left in place."
}

case "${1:-install}" in
  --uninstall|uninstall) uninstall; exit 0 ;;
  --refresh|refresh)
    : "${LOOP_WORKTREE:?set TICKET_LOOP_WORKTREE}"
    git -C "$LOOP_WORKTREE" fetch --quiet origin dev
    git -C "$LOOP_WORKTREE" reset --hard origin/dev
    echo "Refreshed $LOOP_WORKTREE → origin/dev"; exit 0 ;;
  install|"") : ;;
  *) echo "usage: install-cron.sh [install|--refresh|--uninstall]" >&2; exit 2 ;;
esac

: "${LOOP_WORKTREE:?set TICKET_LOOP_WORKTREE=/path/to/a/dedicated/worktree}"
WRAPPER="$LOOP_WORKTREE/.claude/skills/ticket-loop/cron-run.sh"
[ -x "$WRAPPER" ] || { echo "ERROR: wrapper not found/executable: $WRAPPER" >&2; exit 1; }
mkdir -p "$LOOP_WORKTREE/.agent-loop/logs"

# StartCalendarInterval entries: every 30 min, 09:00–20:00 inclusive.
intervals=""
for h in $(seq 9 19); do
  for m in 0 30; do
    intervals="$intervals
    <dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>$m</integer></dict>"
  done
done
intervals="$intervals
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WRAPPER</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>$intervals
  </array>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOOP_WORKTREE/.agent-loop/logs/ticket-loop-launchd.log</string>
  <key>StandardErrorPath</key><string>$LOOP_WORKTREE/.agent-loop/logs/ticket-loop-launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "Installed $LABEL"
echo "  schedule : every 30 min, 09:00–20:00 local (digest on the day's first pass)"
echo "  wrapper  : $WRAPPER"
echo "  plist    : $PLIST"
echo "  logs     : $LOOP_WORKTREE/.agent-loop/logs/ticket-loop-cron.log"
