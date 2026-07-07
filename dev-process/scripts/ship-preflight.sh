#!/usr/bin/env bash
#
# ship-preflight.sh — the deterministic git dance behind an end-of-session
# "wrap up and open a PR" skill, collapsed into two reviewable calls instead of
# ~7 separate permission-gated git commands. The skill keeps the judgement
# (commit messages, PR body, ticket state); this script does the mechanical,
# no-decisions-needed git work.
#
# Subcommands:
#   scripts/ship-preflight.sh assess [--base dev|main]
#       Read-only snapshot of where the branch stands. Refuses to proceed on a
#       long-lived branch (main/dev) — those are not feature branches. Prints:
#       current branch, the base, dirty-tree status, diff --stat, unpushed commit
#       log, and a one-line COUNTS summary the skill can branch on.
#
#   scripts/ship-preflight.sh sync-push [--base dev|main]
#       fetch origin <base> → merge origin/<base> --no-edit → push -u origin HEAD.
#       Run this AFTER the skill has committed everything. Stops (nonzero) on a merge
#       conflict, printing the conflicted files so the skill can resolve them, and
#       stops (nonzero) on a still-dirty tree (commit first). Re-runnable: if already
#       merged/pushed it's a no-op fast-forward.
#
# Base defaults to `dev` (the integration trunk). Pass --base main for a hotfix branch
# that targets main directly.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

CMD="${1:-}"; shift || true
BASE="dev"
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

BRANCH="$(git branch --show-current)"

guard_feature_branch() {
  case "$BRANCH" in
    main|master|dev)
      echo "REFUSE: on long-lived branch '$BRANCH'. Ship from a feature branch." >&2
      exit 3 ;;
  esac
}

case "$CMD" in
  assess)
    guard_feature_branch
    git fetch -q origin "$BASE" || true
    echo "=== branch ==="
    echo "branch: $BRANCH   base: origin/$BASE"
    echo "=== status (porcelain) ==="
    git status --porcelain
    echo "=== diff --stat (vs origin/$BASE) ==="
    git diff --stat "origin/$BASE"...HEAD || true
    echo "=== unpushed/unmerged commits (origin/$BASE..HEAD) ==="
    git log "origin/$BASE..HEAD" --oneline || true
    dirty="$(git status --porcelain | wc -l | tr -d ' ')"
    ahead="$(git rev-list --count "origin/$BASE..HEAD" 2>/dev/null || echo 0)"
    files="$(git diff --name-only "origin/$BASE"...HEAD | wc -l | tr -d ' ')"
    echo "=== COUNTS ==="
    echo "dirty=$dirty ahead=$ahead changed_files=$files"
    if [ "$dirty" = 0 ] && [ "$ahead" = 0 ]; then
      echo "NOTHING_TO_SHIP=1"
    fi
    ;;

  sync-push)
    guard_feature_branch
    if [ -n "$(git status --porcelain)" ]; then
      echo "REFUSE: working tree is dirty — commit everything before sync-push." >&2
      git status --short >&2
      exit 4
    fi
    git fetch -q origin "$BASE"
    if ! git merge "origin/$BASE" --no-edit; then
      echo "CONFLICT: merge of origin/$BASE hit conflicts — resolve then re-run." >&2
      git diff --name-only --diff-filter=U >&2
      exit 5
    fi
    git push -u origin HEAD
    echo "PUSHED: $BRANCH → origin/$BRANCH (synced with origin/$BASE)"
    ;;

  ""|-h|--help)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "unknown subcommand: $CMD (expected: assess | sync-push)" >&2
    exit 2 ;;
esac
