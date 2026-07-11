#!/usr/bin/env bash
#
# local-run.sh — trial the containerized ticket-loop on a laptop before a server.
#
# Same image, same volume shape, same runner as the systemd box path — just local
# Docker, so a tenant can validate the WHOLE loop end to end before touching a
# server. Each subcommand is independently runnable. The recommended order is:
#
#   build → seed → put-env → dry-run   (then, once, a supervised `pass --yes`)
#
# then take the SAME image recipe to a server (the systemd path in README.md).
#
# Config via env:
#   CLAUDE_PIN   the claude version to bake (REQUIRED for `build` — no default)
#   IMAGE        image tag        (default: dev-workflow-agent:local)
#   VOLUME       docker volume    (default: dev-workflow-agent-local)
set -euo pipefail

IMAGE="${IMAGE:-dev-workflow-agent:local}"
VOLUME="${VOLUME:-dev-workflow-agent-local}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"       # skills/ticket-loop/docker -> repo root
DOCKERFILE="skills/ticket-loop/docker/Dockerfile"
NODE_IMAGE="node:22-bookworm-slim"                   # the seed/chown helper image

usage() {
  cat <<EOF
local-run.sh — trial the containerized ticket-loop locally (image: $IMAGE, volume: $VOLUME)

Usage: $0 <command> [args]

  build                          Build \$IMAGE from the repo root. Requires CLAUDE_PIN.
  seed <repo-url> <branch> <name>  Create \$VOLUME (if absent) and clone <branch> into
                                 /home/agent/<name>. Idempotent (skips if .git exists).
  put-env <local-file>           Copy a local env file into the volume as
                                 /home/agent/agent.env (mode 600). Never prints it.
  dry-run <name>                 Run ONE pass with --dry-run: no sends, no builds.
  pass <name> --yes              Run ONE REAL pass. Acts on the real tracker/chat/GitHub.
                                 Requires --yes; stop every other loop for this repo first.
  clean                          Remove the volume and the local image (asks first).

Env: CLAUDE_PIN (build), IMAGE, VOLUME.
EOF
}

# --- helpers ---------------------------------------------------------------

need_docker() {
  command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found on PATH" >&2; exit 1; }
}

volume_exists() { docker volume inspect "$VOLUME" >/dev/null 2>&1; }

# --- subcommands -----------------------------------------------------------

cmd_build() {
  need_docker
  if [ -z "${CLAUDE_PIN:-}" ]; then
    echo "ERROR: CLAUDE_PIN is required (pin the claude version, e.g. CLAUDE_PIN=2.1.0)" >&2
    exit 1
  fi
  echo "Building $IMAGE (claude pin $CLAUDE_PIN) from $REPO_ROOT ..."
  ( cd "$REPO_ROOT" && docker build -f "$DOCKERFILE" \
      --build-arg CLAUDE_CODE_VERSION="$CLAUDE_PIN" -t "$IMAGE" . )
  echo "Built $IMAGE."
}

cmd_seed() {
  need_docker
  local url="${1:-}" branch="${2:-}" name="${3:-}"
  if [ -z "$url" ] || [ -z "$branch" ] || [ -z "$name" ]; then
    echo "ERROR: usage: $0 seed <repo-url> <branch> <name>" >&2
    exit 1
  fi
  volume_exists || { echo "Creating volume $VOLUME ..."; docker volume create "$VOLUME"; }
  if docker run --rm -v "$VOLUME":/home/agent "$NODE_IMAGE" \
       test -d "/home/agent/$name/.git"; then
    echo "Already seeded: /home/agent/$name (has .git) — skipping clone."
    return 0
  fi
  echo "Cloning $url ($branch) into $VOLUME:/home/agent/$name ..."
  docker run --rm -v "$VOLUME":/home/agent "$NODE_IMAGE" \
    bash -lc "apt-get update && apt-get install -y git && \
      git clone --branch '$branch' '$url' '/home/agent/$name'"
  docker run --rm -v "$VOLUME":/home/agent "$NODE_IMAGE" \
    chown -R 10001:10001 "/home/agent/$name"
  echo "Seeded /home/agent/$name. Ensure dev-workflow.yml is at its root."
}

cmd_put_env() {
  need_docker
  local file="${1:-}"
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "ERROR: usage: $0 put-env <local-file>  (an existing env file)" >&2
    exit 1
  fi
  volume_exists || { echo "ERROR: volume $VOLUME does not exist — run 'seed' first" >&2; exit 1; }
  # Piped over stdin; the contents are never echoed to the terminal.
  docker run --rm -i -v "$VOLUME":/home/agent "$NODE_IMAGE" \
    bash -lc 'cat > /home/agent/agent.env && chmod 600 /home/agent/agent.env && \
      chown 10001:10001 /home/agent/agent.env' < "$file"
  echo "Wrote /home/agent/agent.env (mode 600) into $VOLUME."
}

# Run one pass. $1=name, $2="--dry-run" for the safe pass (empty for a real one).
_run_pass() {
  need_docker
  local name="$1" dry="${2:-}"
  volume_exists || { echo "ERROR: volume $VOLUME does not exist — run 'seed' first" >&2; exit 1; }
  # shellcheck disable=SC2086  # $dry is intentionally word-split (empty or --dry-run)
  docker run --rm \
    -v "$VOLUME":/home/agent \
    -e DW_WORK_TREE="/home/agent/$name" \
    "$IMAGE" /opt/dev-workflow/bin/run-pass.sh $dry
}

cmd_dry_run() {
  local name="${1:-}"
  [ -n "$name" ] || { echo "ERROR: usage: $0 dry-run <name>" >&2; exit 1; }
  echo "Dry-run pass for /home/agent/$name (no sends, no builds) ..."
  _run_pass "$name" --dry-run
}

cmd_pass() {
  local name="" yes=""
  for arg in "$@"; do
    case "$arg" in
      --yes) yes=1 ;;
      -*)    echo "ERROR: unknown flag: $arg" >&2; exit 1 ;;
      *)     name="$arg" ;;
    esac
  done
  [ -n "$name" ] || { echo "ERROR: usage: $0 pass <name> --yes" >&2; exit 1; }
  cat <<'WARN' >&2
========================================================================
  WARNING: this is a REAL ticket-loop pass, not a dry run.
  It acts on the REAL tracker, the REAL chat group, and REAL GitHub —
  it can move tickets, post messages, and open/merge PRs.

  The loop's pid-file singleton lock CANNOT arbitrate across machines,
  nor between this container and a host launchd/cron loop. Stop EVERY
  other runner for this repo (box timer, laptop launchd, another
  container) BEFORE you continue, or two loops will collide.
========================================================================
WARN
  if [ -z "$yes" ]; then
    echo "Refusing to run without --yes. Re-run: $0 pass $name --yes" >&2
    exit 1
  fi
  echo "Running a REAL pass for /home/agent/$name ..."
  _run_pass "$name" ""
}

cmd_clean() {
  need_docker
  printf 'Remove volume %s AND image %s? [y/N] ' "$VOLUME" "$IMAGE"
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; return 0 ;;
  esac
  docker volume rm "$VOLUME" 2>/dev/null && echo "Removed volume $VOLUME." || echo "No volume $VOLUME."
  docker image rm "$IMAGE" 2>/dev/null && echo "Removed image $IMAGE." || echo "No image $IMAGE."
}

# --- dispatch --------------------------------------------------------------

main() {
  [ $# -ge 1 ] || { usage; exit 1; }
  local cmd="$1"; shift || true
  case "$cmd" in
    build)    cmd_build "$@" ;;
    seed)     cmd_seed "$@" ;;
    put-env)  cmd_put_env "$@" ;;
    dry-run)  cmd_dry_run "$@" ;;
    pass)     cmd_pass "$@" ;;
    clean)    cmd_clean "$@" ;;
    -h|--help|help) usage ;;
    *) echo "ERROR: unknown command: $cmd" >&2; usage; exit 1 ;;
  esac
}

main "$@"
