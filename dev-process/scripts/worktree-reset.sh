#!/usr/bin/env bash
#
# worktree-reset.sh — start a fresh feature in a git worktree: point it at a NEW
# auto-numbered branch off latest dev, link shared per-machine state, install deps.
# (Reset is the default; pass --link to ONLY (re)create the shared symlinks.)
#
# Branch model (see ../README.md): dev is the integration trunk; feature branches
# start from origin/dev and PR back into dev (no deploy). main is the prod mirror —
# it only advances via a dev→main PR (the deploy). For an urgent prod fix, pass
# --hotfix to base off origin/main instead; PR that straight to main, then
# back-merge main→dev.
#
# Git worktrees share one .git but each has its own working directory, so
# gitignored/untracked files (.env, local scratch, …) are NOT shared. This symlinks
# the shared ones from the canonical main repo into the current worktree.
# Per-worktree build state (venv, node_modules, caches) is intentionally NOT shared.
#
# Usage:
#   scripts/worktree-reset.sh                 # RESET (default): fetch origin/dev, switch this
#                                             # worktree to a NEW auto-numbered branch <slot>-N
#                                             # at origin/dev (e.g. feature-a-3), relink, then
#                                             # install deps. The new branch does NOT track dev.
#   scripts/worktree-reset.sh feat-x          # same, but use the explicit name feat-x
#   scripts/worktree-reset.sh --hotfix        # base off origin/main (urgent prod fix); PR it
#                                             # straight to main, then back-merge main→dev
#   scripts/worktree-reset.sh feat-x --force  # discard unmerged commits on feat-x
#   scripts/worktree-reset.sh --keep-remote   # reset, but skip the merged-remote sweep
#   scripts/worktree-reset.sh --link          # link-only: just (re)create the shared symlinks
#                                             # (the one-time step right after `git worktree add`)
#   scripts/worktree-reset.sh --gc            # GC only: remove dead worktrees (branch merged
#                                             # into origin/dev + tracked-clean + idle >3 days,
#                                             # never a feature-slot dir), then sweep merged
#                                             # local+remote branches. Runs from anywhere,
#                                             # including the canonical repo.
#
# Why auto-numbered branches: a worktree slot (the directory, e.g. feature-a) reusing
# ONE stable branch name makes every new feature inherit the previous one's life — a
# stale base (→ diverged merges and, in Django/Rails, migration-number collisions) and
# a "gone" upstream once its PR merged. A fresh, never-reused <slot>-N branch each time
# always starts at the LATEST origin/dev and lets an earlier feature's PR stay open
# while you start the next (more PRs in flight).
#
# Reset assumes you're starting fresh, so it also sweeps finished work: prunes worktree
# metadata + stale remote-tracking refs, removes dead worktrees (see --gc above — ad-hoc
# and agent worktrees whose branch merged; slot dirs persist), and deletes every branch
# (local AND remote) fully merged into origin/dev. Merged branches lose no commits —
# they're recreated on the next `git push -u`. The remote sweep (git push origin
# --delete) is the one outward action; pass --keep-remote to skip it. (If your repo has
# "automatically delete head branches" enabled on GitHub, the remote sweep is mostly a
# fallback.)

set -euo pipefail

# ── EDIT ME ───────────────────────────────────────────────────────────
# Per-worktree dependency install, run after a reset (each worktree keeps its own
# build state). Examples: "uv sync", "npm ci", "composer install", "bundle install".
# Leave empty to skip.
DEPS_CMD="${WORKTREE_DEPS_CMD:-}"

LINK_ONLY=0; FORCE=0; KEEP_REMOTE=0; HOTFIX=0; GC_ONLY=0; BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --link) LINK_ONLY=1; shift ;;
    --gc) GC_ONLY=1; shift ;;
    --hotfix|--from-main) HOTFIX=1; shift ;;
    --force) FORCE=1; shift ;;
    --keep-remote) KEEP_REMOTE=1; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) BRANCH="$1"; shift ;;
  esac
done

if [ "$LINK_ONLY" = 1 ] && [ -n "$BRANCH" ]; then
  echo "ERROR: --link is link-only and takes no branch name (got '$BRANCH')." >&2
  exit 2
fi
if [ "$LINK_ONLY" = 1 ] && [ "$HOTFIX" = 1 ]; then
  echo "ERROR: --link is link-only; --hotfix only applies to a reset." >&2
  exit 2
fi
if [ "$GC_ONLY" = 1 ] && { [ -n "$BRANCH" ] || [ "$LINK_ONLY" = 1 ] || [ "$HOTFIX" = 1 ]; }; then
  echo "ERROR: --gc is GC-only and combines with nothing but --keep-remote." >&2
  exit 2
fi

# Default shared set, used only when no .worktree-shared manifest is present.
DEFAULT_SHARED=( .env .local .claude/settings.local.json )

WORKTREE_ROOT="$(git rev-parse --show-toplevel)"
COMMON_GIT="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || git rev-parse --git-common-dir)"
CANON="$(cd "$(dirname "$COMMON_GIT")" && pwd)"

# Which gitignored/untracked paths to symlink in. A tracked `.worktree-shared`
# manifest at the repo root is the source of truth (one path per line; `#` comments
# and blank lines ignored; paths carry no spaces) — keeping "what's shared" reviewed
# and version-controlled. Falls back to DEFAULT_SHARED above when absent.
SHARED=()
if [ -f "$CANON/.worktree-shared" ]; then
  while IFS= read -r entry; do
    entry="${entry%%#*}"                                  # drop comments
    entry="$(printf '%s' "$entry" | tr -d '[:space:]')"   # trim (paths have no spaces)
    [ -n "$entry" ] && SHARED+=("$entry")
  done < "$CANON/.worktree-shared"
fi
[ "${#SHARED[@]}" -eq 0 ] && SHARED=( "${DEFAULT_SHARED[@]}" )

# ── sweep helpers (used by reset and --gc) ────────────────────────────
# Remove worktrees whose work is finished: branch fully merged into origin/dev,
# no tracked changes, no untracked files beyond the shared symlinks, and HEAD
# older than 3 days (a freshly-reset worktree sits at origin/dev and must not
# be collected). Slot dirs (feature-a…z) persist across features and are never
# removed — their merged branch is swept on the slot's next reset instead.
sweep_worktrees() {
  local removed=0 now wt base br head_ct stray line p s keep
  now="$(date +%s)"
  while IFS= read -r wt; do
    [ "$wt" = "$CANON" ] && continue
    [ "$wt" = "$WORKTREE_ROOT" ] && continue
    [ -d "$wt" ] || continue
    base="$(basename "$wt")"
    case "$base" in feature-[a-z]) continue ;; esac
    br="$(git -C "$wt" symbolic-ref --quiet --short HEAD || true)"
    [ -z "$br" ] && continue                       # detached HEAD — leave it alone
    case "$br" in main|master|dev) continue ;; esac
    git merge-base --is-ancestor "$br" origin/dev 2>/dev/null || continue
    if [ -n "$(git -C "$wt" status --porcelain --untracked-files=no)" ]; then
      echo "keep   worktree $base — uncommitted tracked changes (branch '$br' IS merged; inspect + remove manually)"
      continue
    fi
    head_ct="$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo "$now")"
    [ $((now - head_ct)) -lt 259200 ] && continue  # HEAD < 3 days old — too fresh
    # Untracked files beyond the shared symlinks could be unshipped work — keep.
    stray=""
    while IFS= read -r line; do
      p="${line#\?\? }"; p="${p%/}"
      keep=1
      for s in "${SHARED[@]}"; do
        if [ "$p" = "$s" ]; then keep=0; break; fi
      done
      [ "$keep" = 1 ] && stray="$stray $p"
    done < <(git -C "$wt" status --porcelain --untracked-files=normal | grep '^??' || true)
    if [ -n "$stray" ]; then
      echo "keep   worktree $base — untracked files beyond shared links:$stray"
      continue
    fi
    # --force: ignored build state (venv, node_modules) and the shared symlinks
    # would otherwise block removal; safety is the checks above, not git's.
    git worktree remove --force "$wt"
    echo "swept  worktree $base (branch '$br' merged into dev)"
    git branch -d "$br" >/dev/null 2>&1 || true
    removed=$((removed+1))
  done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
  echo "Swept $removed dead worktree(s)."
}

sweep_merged_local() {
  local swept=0 b
  for b in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
    case "$b" in main|master|dev|"$BRANCH") continue ;; esac
    if git merge-base --is-ancestor "$b" origin/dev 2>/dev/null \
       && git branch -d "$b" >/dev/null 2>&1; then
      echo "swept  local branch '$b' (merged)"; swept=$((swept+1))
    fi
  done
  echo "Swept $swept merged local branch(es)."
}

sweep_merged_remote() {
  local swept=0 dev_sha r short
  dev_sha="$(git rev-parse origin/dev)"
  for r in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin/); do
    short="${r#origin/}"
    # Never sweep the long-lived branches: main (prod) is usually an ancestor of
    # dev, so it'd otherwise match the "merged into dev" test below.
    case "$short" in main|master|dev|HEAD) continue ;; esac
    # merged into origin/dev but not origin/dev itself
    if [ "$(git rev-parse "$r")" != "$dev_sha" ] \
       && git merge-base --is-ancestor "$r" origin/dev 2>/dev/null \
       && git push -q origin --delete "$short" 2>/dev/null; then
      echo "swept  remote branch 'origin/$short' (merged)"; swept=$((swept+1))
    fi
  done
  echo "Swept $swept merged remote branch(es)."
}

# ── --gc: sweep only, from anywhere (canonical repo included) ─────────
if [ "$GC_ONLY" = 1 ]; then
  git fetch origin --prune
  git worktree prune
  sweep_worktrees
  sweep_merged_local
  if [ "$KEEP_REMOTE" != 1 ]; then sweep_merged_remote; fi
  echo "GC done."
  exit 0
fi

if [ "$CANON" = "$WORKTREE_ROOT" ]; then
  echo "This is the canonical (main) repo at $CANON — run from a linked worktree (or pass --gc)."
  exit 0
fi

# ── reset (default): fresh branch off latest origin/dev (origin/main if --hotfix) ──
if [ "$LINK_ONLY" != 1 ]; then
  SLOT="$(basename "$WORKTREE_ROOT")"
  # Refuse on a dirty tree — tracked changes only (the shared symlinks show as
  # untracked, so -uno keeps them from blocking a legitimate reset).
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "ERROR: uncommitted changes in this worktree — commit / stash / ship first." >&2
    git status --short --untracked-files=no >&2
    exit 1
  fi
  # One fetch: refresh origin/dev + origin/main AND prune remote-tracking refs whose
  # upstream was deleted on merge. Do it before naming so the auto-increment below
  # sees the true set of live local + remote branches.
  git fetch origin --prune

  if ! git show-ref --verify --quiet refs/remotes/origin/dev; then
    echo "ERROR: origin/dev not found. New branches start from dev (see ../README.md)." >&2
    echo "Create it once:  git push origin origin/main:refs/heads/dev   (then set dev as the GitHub default branch)." >&2
    exit 1
  fi
  if [ "$HOTFIX" = 1 ]; then BASE_REF="origin/main"; else BASE_REF="origin/dev"; fi

  # Branch name. Explicit arg wins; otherwise mint a brand-new <slot>-N (the smallest
  # number above every existing local/remote <slot>-N).
  if [ -z "$BRANCH" ]; then
    n=1
    for ref in $(git for-each-ref --format='%(refname:short)' \
                   "refs/heads/$SLOT-*" "refs/remotes/origin/$SLOT-*"); do
      suffix="${ref##*-}"                          # last dash-segment
      case "$suffix" in ''|*[!0-9]*) continue ;; esac   # only pure-number suffixes count
      [ "$suffix" -ge "$n" ] && n=$((suffix + 1))
    done
    BRANCH="$SLOT-$n"
  fi
  # A feature worktree must never sit on a long-lived branch: main is the prod-deploy
  # mirror, dev is the integration trunk — you branch OFF them, you don't work ON them here.
  case "$BRANCH" in
    main|master|dev)
      echo "ERROR: refusing to put a worktree on '$BRANCH' — that's a long-lived branch (main=prod, dev=trunk)." >&2
      echo "Pass an explicit feature name: scripts/worktree-reset.sh <name>" >&2
      exit 1 ;;
  esac
  # Don't silently nuke unmerged commits on an existing target branch. Only reachable
  # when an explicit branch name is reused; auto-numbered branches are always new.
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    unmerged="$(git rev-list --count "$BASE_REF..$BRANCH" 2>/dev/null || echo 0)"
    if [ "$unmerged" -gt 0 ] && [ "$FORCE" != 1 ]; then
      echo "ERROR: branch '$BRANCH' has $unmerged commit(s) not on $BASE_REF." >&2
      echo "Ship them, pass a new explicit name, or pass --force to discard." >&2
      exit 1
    fi
  fi
  PREV="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"  # branch we're leaving
  echo "Reset → fresh branch '$BRANCH' at $BASE_REF"
  # --no-track is critical: without it the new branch tracks the base, so a bare
  # `git push` targets dev/main directly instead of the feature branch. The feature
  # branch gets its own upstream on first `git push -u origin <branch>`.
  git switch --no-track -C "$BRANCH" "$BASE_REF"
  echo

  # ── sweep finished work (we're starting a new feature) ──────────────
  # Prune worktree metadata for removed dirs, remove dead worktrees (which frees
  # the branches they pinned), then delete every branch (local + remote) fully
  # merged into origin/dev. `git branch -d` independently refuses unmerged branches
  # and any branch checked out in another worktree, so this can't drop live work.
  git worktree prune
  sweep_worktrees
  sweep_merged_local
  if [ "$KEEP_REMOTE" != 1 ]; then sweep_merged_remote; fi
  # If we left an earlier feature branch behind with unshipped work, say so — it's
  # intentionally kept (its PR may still be open), just no longer checked out here.
  if [ -n "${PREV:-}" ] && [ "$PREV" != "$BRANCH" ] \
     && git show-ref --verify --quiet "refs/heads/$PREV"; then
    left="$(git rev-list --count "origin/dev..$PREV" 2>/dev/null || echo 0)"
    [ "$left" -gt 0 ] && echo "note   kept earlier branch '$PREV' ($left unshipped commit(s)) — still here locally."
  fi
  echo
fi

# ── link shared gitignored state ──────────────────────────────────────
linked=0; skipped=0; backed=0
for rel in "${SHARED[@]}"; do
  src="$CANON/$rel"
  dst="$WORKTREE_ROOT/$rel"
  if [ ! -e "$src" ] && [ ! -L "$src" ]; then
    echo "skip   $rel — not present in main"; skipped=$((skipped+1)); continue
  fi
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
    echo "ok     $rel — already linked"; skipped=$((skipped+1)); continue
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    bak="$dst.pre-link-bak.$(date +%s)"; mv "$dst" "$bak"
    echo "backup $rel → $(basename "$bak")"; backed=$((backed+1))
  fi
  ln -s "$src" "$dst"
  echo "link   $rel → $src"; linked=$((linked+1))
done
echo
echo "Linked $linked, already-ok $skipped, backed-up $backed."

# ── reset (default): install this worktree's own deps ─────────────────
if [ "$LINK_ONLY" != 1 ]; then
  if [ -n "$DEPS_CMD" ]; then
    echo
    echo "deps: $DEPS_CMD (this worktree's own build state)…"
    ( cd "$WORKTREE_ROOT" && eval "$DEPS_CMD" )
  fi
  echo
  echo "Ready: worktree on '$BRANCH' at $BASE_REF, shared state linked."
else
  echo "Link-only (--link): per-worktree build state is NOT shared — install deps here,"
  echo "or run without --link to reset + install in one go."
fi
