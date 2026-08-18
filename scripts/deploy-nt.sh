#!/usr/bin/env bash
# deploy-nt.sh — manual prod rollout to the orchestrator box after a release
# merges to main. There is NO auto-deploy: merging the dev→main PR is the
# release marker (`deploy.trigger: merge-main`); a human runs THIS script to
# roll the box.
#
# What it does:
#   1. image   — wraps skills/ticket-loop/orchestrator/deploy.sh `deploy`:
#                push $BRANCH, remote pull, rebuild the dw-agent image, recreate
#                the dw-orchestrator container (drain-safe).
#   2. env     — OPT-IN (--with-env / --env-only): reconcile-then-push of the
#                .local/ env masters per .local/deploy-manifest. NEVER a blind
#                copy: per file it compares sha256 against the live volume copy,
#                shows which KEY NAMES changed (never values), and requires a
#                typed "yes" before pushing that file. Skips identical files.
#
# ⚠️ The volume copies on the box can be NEWER than .local/ (box-side edits, e.g.
# the 2026-07-15 shared-token consolidation was done directly on the box). A
# file that "differs" is not automatically stale on the box — read the changed
# keys and decide direction consciously. If the box is right, update .local/
# instead of pushing.
#
#   scripts/deploy-nt.sh                # image only (safe default)
#   scripts/deploy-nt.sh --with-env     # image, then env reconcile/push
#   scripts/deploy-nt.sh --env-only     # env reconcile/push only
#
# Env (defaults match the nt deployment): HOST, BRANCH, VOLUME, CONTAINER —
# forwarded to orchestrator/deploy.sh for the image step.
set -euo pipefail

HOST="${HOST:-nt}"
BRANCH="${BRANCH:-main}"
VOLUME="${VOLUME:-dw-agent}"
CONTAINER="${CONTAINER:-dw-orchestrator}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORCH_DEPLOY="$ROOT/skills/ticket-loop/orchestrator/deploy.sh"
LOCAL_DIR="$ROOT/.local"
MANIFEST="$LOCAL_DIR/deploy-manifest"
MOUNT="/var/lib/docker/volumes/$VOLUME/_data"

DO_IMAGE=1 DO_ENV=0
case "${1:-}" in
  --with-env) DO_ENV=1 ;;
  --env-only) DO_IMAGE=0; DO_ENV=1 ;;
  "") ;;
  *) echo "usage: deploy-nt.sh [--with-env|--env-only]" >&2; exit 2 ;;
esac

key_names() {  # print VAR names of an env-ish file ('#'/blank ignored)
  grep -Eo '^[A-Za-z_][A-Za-z0-9_]*=' "$1" 2>/dev/null | sed 's/=$//' | sort -u
}

push_file() {  # push_file <local> <volume-path> <mode>
  local src="$1" dst="$2" mode="$3" tmp="/tmp/dw-push.$$"
  # Two separate ssh calls on purpose: piping file data AND a heredoc script in
  # one call loses the data (the heredoc claims stdin).
  ssh "$HOST" "cat > $tmp" < "$src"
  ssh "$HOST" "sudo install -o 10001 -g 10001 -m $mode $tmp $MOUNT${dst#/home/agent} && rm -f $tmp"
}

env_sync() {
  [ -f "$MANIFEST" ] || { echo "no $MANIFEST — nothing to push" >&2; return 1; }
  local pushed=0 line src dst mode lsha rsha rpath
  while read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    set -- $line; src="$LOCAL_DIR/$1" dst="$2" mode="$3"
    [ -f "$src" ] || { echo "SKIP $1 — not in .local/"; continue; }
    rpath="$MOUNT${dst#/home/agent}"
    lsha="$(shasum -a 256 "$src" | cut -d' ' -f1)"
    rsha="$(ssh "$HOST" "sudo sha256sum $rpath 2>/dev/null | cut -d' ' -f1" || true)"
    if [ "$lsha" = "$rsha" ]; then echo "OK   $1 — identical on box"; continue; fi
    echo "DIFF $1 → $dst  (box copy ${rsha:+differs}${rsha:-missing})"
    # Key-name-level diff only — values never leave the files.
    ssh "$HOST" "sudo cat $rpath 2>/dev/null" > "/tmp/dw-remote.$$" || true
    comm -13 <(key_names "/tmp/dw-remote.$$") <(key_names "$src") | sed 's/^/       + local-only key: /'
    comm -23 <(key_names "/tmp/dw-remote.$$") <(key_names "$src") | sed 's/^/       - box-only key:   /'
    rm -f "/tmp/dw-remote.$$"
    printf '     push .local/%s over the box copy? [yes/NO] ' "$1"
    read -r ans </dev/tty
    if [ "$ans" = "yes" ]; then push_file "$src" "$dst" "$mode"; echo "     PUSHED"; pushed=1
    else echo "     skipped"; fi
  done < "$MANIFEST"
  if [ "$pushed" = 1 ]; then
    echo "restarting $CONTAINER to load new config…"
    ssh "$HOST" "docker restart $CONTAINER" >/dev/null
  fi
}

# Releases merge on GitHub, so the local $BRANCH ref lags behind origin after
# every release — fast-forward it first or deploy.sh's push step rejects.
if [ "$DO_IMAGE" = 1 ]; then
  git -C "$ROOT" fetch origin "$BRANCH:$BRANCH" 2>/dev/null \
    || echo "note: could not fast-forward local $BRANCH (checked out or diverged) — deploy.sh push may fail"
  HOST="$HOST" BRANCH="$BRANCH" VOLUME="$VOLUME" CONTAINER="$CONTAINER" "$ORCH_DEPLOY" deploy
fi
[ "$DO_ENV" = 1 ] && env_sync
echo "done."
