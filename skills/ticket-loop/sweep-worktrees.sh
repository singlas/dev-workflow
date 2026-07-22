#!/bin/bash
# sweep-worktrees.sh — the agent-tier worktree/branch prune policy, the twin of
# the laptop-side `worktree-reset.sh --gc`. The ticket-loop's build subagents make
# isolated worktrees under `<repo>/.claude/worktrees/agent-*` plus local branches
# (`agent/<key>`, `worktree-agent-*`), and nothing in the agent tier ever deletes
# them — so disk leaks. This reclaims them, safely, pre-pass under the singleton
# lock (no build can be in flight), mirroring worktree-reset.sh's careful style.
#
# Standalone-callable so it's testable and usable by hand via `docker exec`:
#   sweep-worktrees.sh <repo-dir> [<repo-dir> ...]
#
# Per repo, in order:
#   1. `git worktree prune` — clear metadata for already-deleted dirs.
#   2. Remove ONLY loop-owned worktrees under .claude/worktrees/ whose checked-out
#      branch matches `agent/*` or `worktree-agent-*` (`git worktree remove --force`);
#      then `rm -rf` orphan dirs under .claude/worktrees/ named `agent-*` that are NOT
#      registered worktrees. Any other worktree (a human's, a `feature-x`) is left
#      alone. Branches survive worktree removal — work is never lost.
#   3. Delete local `agent/*` / `worktree-agent-*` branches merged into origin/<base>:
#      ancestry check first (`git merge-base --is-ancestor`); for `agent/*` only, a
#      squash-merge fallback via `gh pr list --head <branch> --state merged` (branches
#      always have a PR). `worktree-agent-*` harness branches never get PRs, so they
#      get ancestry-only. No gh / no network / query error → skip the fallback,
#      never guess. Never touch the checked-out branch, base, prod, or main/master/dev.
#   4. No remote sweep — GitHub auto-delete-on-merge owns remote branches.
#
# Never exits nonzero in a way that would abort a pass (set -uo, no -e; always exit 0);
# logs what it swept/kept to stdout. `TICKET_LOOP_NO_SWEEP=1` makes it a no-op.
set -uo pipefail

if [ "${TICKET_LOOP_NO_SWEEP:-}" = "1" ]; then
  echo "sweep: TICKET_LOOP_NO_SWEEP=1 — skipping"
  exit 0
fi

if [ "$#" -eq 0 ]; then
  echo "usage: sweep-worktrees.sh <repo-dir> [<repo-dir> ...]" >&2
  exit 0
fi

# ── config reader (dev-workflow.yml + dw-config.py) — same idiom as cron-run.sh ──
# DW_ROOT is where this script + its siblings live (dw-config.py in the image);
# on a framework checkout it also lives at <repo>/dev-workflow/dw-config.py.
DW_ROOT="${DW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
DW_RUN=""
if [ -n "${DW_PYTHON:-}" ]; then
  DW_RUN="$DW_PYTHON"
elif command -v uv >/dev/null 2>&1; then
  DW_RUN="uv run --quiet --no-project"
elif command -v python3 >/dev/null 2>&1; then
  DW_RUN="python3"
fi

# cfg <repo> <dotted.path> [default] — print the repo's config value, else default.
cfg() {
  local repo="$1" key="$2" def="${3:-}" cfgfile="$1/dev-workflow.yml" py=""
  local _c
  for _c in "$DW_ROOT/dw-config.py" "$repo/dev-workflow/dw-config.py"; do
    [ -f "$_c" ] && { py="$_c"; break; }
  done
  if [ -f "$cfgfile" ] && [ -n "$py" ] && [ -n "$DW_RUN" ]; then
    $DW_RUN "$py" "$cfgfile" "$key" 2>/dev/null && return 0
  fi
  [ -n "$def" ] && { printf '%s\n' "$def"; return 0; }
  return 1
}

# ── squash-merge fallback: does <branch> have a merged PR in <repo>? ──
# Bounded, repo-scoped, degrades silently. `gh pr list` targets the cwd repo, so
# run it inside <repo>. Missing gh / unauthenticated / network error / no PR → 1.
gh_pr_merged() {  # $1 repo, $2 branch
  command -v gh >/dev/null 2>&1 || return 1
  local out to=""
  command -v timeout >/dev/null 2>&1 && to="timeout 20"
  out="$( cd "$1" 2>/dev/null && $to gh pr list --head "$2" --state merged --limit 1 --json number 2>/dev/null )" || return 1
  case "$out" in
    *'"number"'*) return 0 ;;
    *) return 1 ;;
  esac
}

# ── is <branch> loop-owned (the loop's own naming)? ──
loop_owned() {  # $1 branch
  case "$1" in agent/*|worktree-agent-*) return 0 ;; *) return 1 ;; esac
}

sweep_repo() {
  local repo="$1"
  if [ ! -d "$repo" ] || ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    echo "sweep: skip $repo — not a git repo"
    return 0
  fi
  # Normalize to the physical path so the wt_dir prefix test below matches git's
  # porcelain output, which reports resolved (symlink-free) absolute paths.
  repo="$(cd "$repo" && pwd -P)"
  echo "sweep: $repo"

  local base prod current
  # Base branch from config, else the repo dir's current checked-out branch.
  current="$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  base="$(cfg "$repo" repo.base_branch "" || true)"
  [ -n "$base" ] || base="${current:-dev}"
  prod="$(cfg "$repo" repo.prod_branch main || echo main)"

  # 1. prune metadata for already-deleted worktree dirs.
  git -C "$repo" worktree prune 2>/dev/null || true

  local wt_dir="$repo/.claude/worktrees"

  # 2. Remove loop-owned worktrees under .claude/worktrees/, then orphan agent-* dirs.
  local cur_wt="" cur_br="" removed=0
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) cur_wt="${line#worktree }" ;;
      "branch "*)   cur_br="${line#branch }"; cur_br="${cur_br#refs/heads/}" ;;
      "")  # end of a porcelain record
        if [ -n "$cur_wt" ]; then
          case "$cur_wt/" in
            "$wt_dir"/*)
              if [ -n "$cur_br" ] && loop_owned "$cur_br"; then
                if git -C "$repo" worktree remove --force "$cur_wt" 2>/dev/null; then
                  echo "  swept  worktree $(basename "$cur_wt") (branch '$cur_br')"
                  removed=$((removed+1))
                else
                  echo "  keep   worktree $(basename "$cur_wt") — could not remove (branch '$cur_br')"
                fi
              else
                echo "  keep   worktree $(basename "$cur_wt") — branch '${cur_br:-detached}' not loop-owned"
              fi
              ;;
          esac
        fi
        cur_wt=""; cur_br="" ;;
    esac
  done < <(git -C "$repo" worktree list --porcelain 2>/dev/null; printf '\n')

  # Orphan dirs: named agent-* under .claude/worktrees/ but not a registered worktree.
  if [ -d "$wt_dir" ]; then
    local registered d
    registered="$(git -C "$repo" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')"
    for d in "$wt_dir"/agent-*; do
      [ -e "$d" ] || continue          # no glob match
      [ -d "$d" ] || continue
      local abs
      abs="$(cd "$d" 2>/dev/null && pwd -P || echo "$d")"
      if printf '%s\n' "$registered" | grep -Fxq "$abs"; then
        continue                        # still a live worktree — leave it
      fi
      rm -rf "$d" && echo "  swept  orphan dir $(basename "$d")"
    done
  fi
  echo "  worktrees: removed $removed loop-owned."

  # 3. Delete merged loop-owned local branches.
  local b swept=0
  for b in $(git -C "$repo" for-each-ref --format='%(refname:short)' \
               'refs/heads/agent/*' 'refs/heads/worktree-agent-*' 2>/dev/null); do
    loop_owned "$b" || continue
    case "$b" in "$base"|"$prod"|main|master|dev|"$current") continue ;; esac
    if git -C "$repo" merge-base --is-ancestor "$b" "origin/$base" 2>/dev/null; then
      if git -C "$repo" branch -D "$b" >/dev/null 2>&1; then
        echo "  swept  local branch '$b' (merged into $base)"; swept=$((swept+1))
      fi
    else
      # Squash-merge fallback: agent/* only (worktree-agent-* never get a PR).
      case "$b" in
        agent/*)
          if gh_pr_merged "$repo" "$b"; then
            if git -C "$repo" branch -D "$b" >/dev/null 2>&1; then
              echo "  swept  local branch '$b' (squash-merged PR)"; swept=$((swept+1))
            fi
          fi
          ;;
      esac
    fi
  done
  echo "  branches: deleted $swept merged loop-owned."
}

for repo in "$@"; do
  sweep_repo "$repo"
done

exit 0
