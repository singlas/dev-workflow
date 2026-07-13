#!/usr/bin/env bash
#
# deploy.sh — push local changes to the orchestrator box in one command.
#
# There is NO auto-deploy: `git push` alone changes nothing on the box (nothing
# there watches GitHub). This script runs the manual chain the runbook (§10)
# spells out — push → remote pull → rebuild → recreate → verify — over ssh, and
# is the executable source of truth for the `docker run` flags.
#
# Pick the command by WHAT changed (mirrors the runbook's three update classes):
#   deploy   — code baked into the image (telegram.py, orchestrator.sh, orch.py,
#              run-pass.sh, cron-run.sh, queue-count.py, SKILL.md, Dockerfile).
#              Full chain: rebuild the image, recreate the container.
#   restart  — config on the VOLUME (roster.yml, orch.env, a project's *.env).
#              No rebuild; `docker restart` re-reads them (boot lock-clear +
#              crash recovery make it safe any time). Rewrite the volume file
#              first (runbook §4/§10), THEN run this.
#   status   — container state + a check that the running code matches, + tail.
#   logs     — follow the live decision log.
#
# Docs-only changes (README, specs) need neither: just `git pull` on the box for
# reference. This script never touches secrets/roster/env files — those hold
# credentials and live in <box>:~/dev-workflow/.local + the volume.
#
# Config via env (defaults match the nt deployment):
#   HOST         ssh target                 (default: nt)
#   CLAUDE_PIN   claude version to bake     (default: 2.1.207) — also the tag
#   IMAGE        image tag                  (default: dw-agent:$CLAUDE_PIN)
#   VOLUME       docker volume              (default: dw-agent)
#   CONTAINER    container name             (default: dw-orchestrator)
#   REMOTE_DIR   framework checkout on box  (default: ~/dev-workflow)
#   BRANCH       branch to push/pull        (default: main)
set -euo pipefail

HOST="${HOST:-nt}"
CLAUDE_PIN="${CLAUDE_PIN:-2.1.207}"
IMAGE="${IMAGE:-dw-agent:$CLAUDE_PIN}"
VOLUME="${VOLUME:-dw-agent}"
CONTAINER="${CONTAINER:-dw-orchestrator}"
REMOTE_DIR="${REMOTE_DIR:-dev-workflow}"          # relative to the box's $HOME (ssh lands there)
BRANCH="${BRANCH:-main}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"   # skills/ticket-loop/orchestrator -> repo root

usage() {
  cat <<EOF
deploy.sh — one-command deploy to the orchestrator box (host: $HOST, container: $CONTAINER)

Usage: $0 <command> [--no-push]

  deploy [--no-push]   Full code deploy: push $BRANCH, remote pull, rebuild $IMAGE,
                       recreate the container, verify. --no-push redeploys the
                       box's current HEAD without pushing local commits first.
  restart              Config-only reload (roster.yml / orch.env / *.env already
                       rewritten on the volume): docker restart, no rebuild.
  status               Container state + running-code check + recent decisions.
  logs                 Follow the live decision log (Ctrl-C to stop).

Env: HOST, CLAUDE_PIN, IMAGE, VOLUME, CONTAINER, REMOTE_DIR, BRANCH.
EOF
}

log() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

# The canonical run recipe (runbook §10). No -e flags: the ops channel + shared
# default bot come from orch.env on the volume; per-project secrets from each
# project's env file. Keep this the ONE place these flags live.
remote_recreate_script() {
  cat <<'REMOTE'
set -euo pipefail
IMAGE="$1"; VOLUME="$2"; CONTAINER="$3"
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "stopping $CONTAINER (SIGTERM drain — waits for any in-flight pass) ..."
  docker stop "$CONTAINER" >/dev/null
  docker rm "$CONTAINER" >/dev/null
fi
docker run -d --name "$CONTAINER" \
  --restart unless-stopped --init \
  --network host \
  --memory=2g --memory-swap=2g --cpus=1 --pids-limit 512 \
  --stop-timeout 5460 \
  --log-opt max-size=10m --log-opt max-file=3 \
  -v "$VOLUME":/home/agent \
  "$IMAGE" /opt/dev-workflow/bin/orchestrator.sh >/dev/null
echo "recreated $CONTAINER from $IMAGE"
REMOTE
}

verify_script() {
  cat <<'REMOTE'
set -uo pipefail
CONTAINER="$1"
sleep 6
echo "== container =="
docker ps --filter "name=$CONTAINER" --format "{{.Status}}  image={{.Image}}" || true
echo "== running code (expect >=1 / >=1) =="
printf 'peek-only pre-check: '; docker exec "$CONTAINER" grep -c "no pending messages" /opt/dev-workflow/bin/orchestrator.sh 2>/dev/null || echo 0
printf 'shared-bot mode:     '; docker exec "$CONTAINER" grep -c "TELEGRAM_SHARED_BOT" /opt/dev-workflow/bin/telegram.py 2>/dev/null || echo 0
echo "== recent decisions =="
docker logs --since 5m "$CONTAINER" 2>&1 | tail -6 || true
REMOTE
}

cmd_deploy() {
  local push=1
  for arg in "$@"; do
    case "$arg" in
      --no-push) push=0 ;;
      *) echo "ERROR: unknown flag: $arg" >&2; exit 1 ;;
    esac
  done

  if [ "$push" = 1 ]; then
    log "push $BRANCH → origin"
    if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
      echo "WARNING: working tree has uncommitted changes — only COMMITTED work on"
      echo "         $BRANCH will deploy. Commit first, or re-run with --no-push." >&2
    fi
    git -C "$REPO_ROOT" push origin "$BRANCH"
  else
    log "skipping push (--no-push) — deploying the box's current HEAD after pull"
  fi

  log "remote pull + rebuild $IMAGE (claude pin $CLAUDE_PIN) on $HOST"
  ssh "$HOST" bash -s -- "$REMOTE_DIR" "$BRANCH" "$CLAUDE_PIN" "$IMAGE" "$VOLUME" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"; BRANCH="$2"; CLAUDE_PIN="$3"; IMAGE="$4"; VOLUME="$5"
cd "$REMOTE_DIR"
git pull --ff-only origin "$BRANCH"
CLAUDE_PIN="$CLAUDE_PIN" IMAGE="$IMAGE" VOLUME="$VOLUME" \
  skills/ticket-loop/docker/local-run.sh build
REMOTE

  log "recreate $CONTAINER on $HOST"
  ssh "$HOST" bash -s -- "$IMAGE" "$VOLUME" "$CONTAINER" < <(remote_recreate_script)

  log "verify"
  ssh "$HOST" bash -s -- "$CONTAINER" < <(verify_script)
  echo
  echo "Deployed. Docs-only follow-ups (README/specs) need no redeploy — the box"
  echo "already pulled them above."
}

cmd_restart() {
  log "config reload — docker restart $CONTAINER on $HOST (no rebuild)"
  ssh "$HOST" docker restart "$CONTAINER"
  ssh "$HOST" bash -s -- "$CONTAINER" < <(verify_script)
}

cmd_status() {
  ssh "$HOST" bash -s -- "$CONTAINER" < <(verify_script)
}

cmd_logs() {
  exec ssh "$HOST" docker logs -f "$CONTAINER"
}

main() {
  [ $# -ge 1 ] || { usage; exit 1; }
  local cmd="$1"; shift || true
  case "$cmd" in
    deploy)  cmd_deploy "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status "$@" ;;
    logs)    cmd_logs "$@" ;;
    -h|--help|help) usage ;;
    *) echo "ERROR: unknown command: $cmd" >&2; usage; exit 1 ;;
  esac
}

main "$@"
