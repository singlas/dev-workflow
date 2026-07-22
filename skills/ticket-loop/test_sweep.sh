#!/bin/bash
# Offline smoke test for sweep-worktrees.sh — no network, no real gh, no docker.
# Builds a temp origin + clone with the loop's own worktrees/branches and asserts
# the sweep reclaims exactly the loop-owned dead ones and nothing else.
#
# Run: bash skills/ticket-loop/test_sweep.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP="$HERE/sweep-worktrees.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=0
fail() { echo "FAIL: $*" >&2; FAILED=1; }

git_q() { git -c init.defaultBranch=dev -c user.email=t@t -c user.name=t -c commit.gpgsign=false "$@"; }

# build_fixture <dir> — a fresh origin + clone with:
#   agent/merged        — true-merged into origin/dev (ancestry)     → deletable
#   agent/unmerged      — never merged                                → kept
#   agent/squash        — squash-merged (tip NOT an ancestor)         → deletable only via gh
#   worktree-agent-1    — true-merged into origin/dev (ancestry)      → deletable
#   feature-x           — a NON-loop branch                           → kept
# worktrees under .claude/worktrees/: agent-merged (agent/merged), agent-squash
#   (agent/squash), wt-agent-1 (worktree-agent-1), feature-x (feature-x, NON-loop).
# plus an orphan dir .claude/worktrees/agent-orphan (not a registered worktree).
build_fixture() {
  local dir="$1" origin="$1/origin" clone="$1/clone"
  mkdir -p "$dir"
  git_q init --bare -q "$origin"
  git -C "$origin" symbolic-ref HEAD refs/heads/dev
  git_q clone -q "$origin" "$clone" 2>/dev/null
  ( cd "$clone"
    git_q checkout -q -b dev 2>/dev/null || git_q checkout -q dev
    echo base > base.txt; git_q add -A; git_q commit -q -m "base"

    # agent/merged — true merge into dev, pushed → ancestor of origin/dev
    git_q checkout -q -b agent/merged dev
    echo m > m.txt; git_q add -A; git_q commit -q -m "merged work"
    git_q checkout -q dev
    git_q merge -q --no-ff agent/merged -m "merge agent/merged"

    # worktree-agent-1 — true merge into dev, pushed → ancestor of origin/dev
    git_q checkout -q -b worktree-agent-1 dev
    echo w > w.txt; git_q add -A; git_q commit -q -m "harness work"
    git_q checkout -q dev
    git_q merge -q --no-ff worktree-agent-1 -m "merge worktree-agent-1"

    # agent/squash — branch tip is NOT reachable from dev (a distinct squash commit is)
    git_q checkout -q -b agent/squash dev
    echo squashed > s.txt; git_q add -A; git_q commit -q -m "squash work on branch"
    git_q checkout -q dev
    echo squashed > s.txt; git_q add -A; git_q commit -q -m "squashed: s.txt (distinct commit)"

    git_q push -q origin dev              # origin/dev now carries the merges + squash

    # agent/unmerged — real unmerged work
    git_q checkout -q -b agent/unmerged dev
    echo u > u.txt; git_q add -A; git_q commit -q -m "unmerged work"
    git_q checkout -q dev

    # feature-x — a human/non-loop branch
    git_q branch feature-x dev

    # worktrees under .claude/worktrees/
    git_q worktree add -q .claude/worktrees/agent-merged agent/merged
    git_q worktree add -q .claude/worktrees/agent-squash agent/squash
    git_q worktree add -q .claude/worktrees/wt-agent-1 worktree-agent-1
    git_q worktree add -q .claude/worktrees/feature-x feature-x

    # orphan dir named agent-* that is NOT a registered worktree
    mkdir -p .claude/worktrees/agent-orphan
    echo junk > .claude/worktrees/agent-orphan/leftover.txt
  )
}

# stub gh reporting agent/squash as merged; anything else → no PR.
mk_gh_ok() {
  mkdir -p "$1"
  cat > "$1/gh" <<'EOF'
#!/bin/bash
head=""
while [ $# -gt 0 ]; do case "$1" in --head) head="$2"; shift 2;; *) shift;; esac; done
if [ "$head" = "agent/squash" ]; then echo '[{"number":1}]'; else echo '[]'; fi
EOF
  chmod +x "$1/gh"
}
# stub gh that always fails (simulate no network / unauthenticated).
mk_gh_fail() {
  mkdir -p "$1"
  printf '#!/bin/bash\nexit 3\n' > "$1/gh"
  chmod +x "$1/gh"
}

has_branch()   { git -C "$1" show-ref --verify --quiet "refs/heads/$2"; }
wt_registered(){ git -C "$1" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | grep -Fq "/.claude/worktrees/$2"; }

# ── Scenario A: full sweep with a working gh (the happy path) ──
A="$TMP/A"; build_fixture "$A"; CLONE="$A/clone"
mk_gh_ok "$TMP/binA"
PATH="$TMP/binA:$PATH" bash "$SWEEP" "$CLONE" > "$TMP/A.log" 2>&1 || fail "sweep A exited nonzero"

has_branch "$CLONE" "agent/merged"     && fail "A: agent/merged (ancestry-merged) not deleted"
has_branch "$CLONE" "worktree-agent-1" && fail "A: worktree-agent-1 (ancestry-merged) not deleted"
has_branch "$CLONE" "agent/squash"     && fail "A: agent/squash (squash-merged, gh says merged) not deleted"
has_branch "$CLONE" "agent/unmerged"   || fail "A: agent/unmerged wrongly deleted"
has_branch "$CLONE" "feature-x"        || fail "A: feature-x (non-loop) wrongly deleted"

[ -d "$CLONE/.claude/worktrees/agent-merged" ] && fail "A: loop worktree agent-merged not removed"
[ -d "$CLONE/.claude/worktrees/agent-squash" ] && fail "A: loop worktree agent-squash not removed"
[ -d "$CLONE/.claude/worktrees/wt-agent-1" ]   && fail "A: loop worktree wt-agent-1 not removed"
[ -d "$CLONE/.claude/worktrees/agent-orphan" ] && fail "A: orphan dir agent-orphan not removed"
[ -d "$CLONE/.claude/worktrees/feature-x" ]    || fail "A: non-loop worktree feature-x wrongly removed"
wt_registered "$CLONE" "feature-x"             || fail "A: feature-x worktree no longer registered"

# ── Scenario B: TICKET_LOOP_NO_SWEEP=1 is a no-op ──
B="$TMP/B"; build_fixture "$B"; CLONEB="$B/clone"
mk_gh_ok "$TMP/binB"
PATH="$TMP/binB:$PATH" TICKET_LOOP_NO_SWEEP=1 bash "$SWEEP" "$CLONEB" > "$TMP/B.log" 2>&1 || fail "sweep B exited nonzero"

has_branch "$CLONEB" "agent/merged"          || fail "B: NO_SWEEP deleted agent/merged"
has_branch "$CLONEB" "agent/squash"          || fail "B: NO_SWEEP deleted agent/squash"
[ -d "$CLONEB/.claude/worktrees/agent-merged" ] || fail "B: NO_SWEEP removed a loop worktree"
[ -d "$CLONEB/.claude/worktrees/agent-orphan" ] || fail "B: NO_SWEEP removed the orphan dir"

# ── Scenario C: a FAILING gh leaves the squash-merged branch in place ──
C="$TMP/C"; build_fixture "$C"; CLONEC="$C/clone"
mk_gh_fail "$TMP/binC"
PATH="$TMP/binC:$PATH" bash "$SWEEP" "$CLONEC" > "$TMP/C.log" 2>&1 || fail "sweep C exited nonzero"

has_branch "$CLONEC" "agent/merged"  && fail "C: agent/merged (ancestry) should still be deleted"
has_branch "$CLONEC" "agent/squash"  || fail "C: squash branch deleted despite failing gh (must degrade to keep)"
has_branch "$CLONEC" "agent/unmerged" || fail "C: agent/unmerged wrongly deleted"

if [ "$FAILED" = 0 ]; then
  echo "PASS — sweep A (ancestry+squash+worktrees+orphan), B (NO_SWEEP no-op), C (gh-fail degrade)"
else
  echo "--- A.log ---"; cat "$TMP/A.log"
  echo "--- C.log ---"; cat "$TMP/C.log"
  exit 1
fi
