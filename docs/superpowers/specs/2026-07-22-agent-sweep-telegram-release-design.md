# Agent-tier worktree/branch sweep + Telegram-triggered release

**Status:** approved design, pending implementation plan.
**Captured:** 2026-07-22
**Related:** `2026-07-16-worktree-sweep-squash-merged-branches.md` (parked — laptop-side squash detection; this spec implements the agent-tier variant of its "ask the host" option).

## Problem

1. **Disk leak on the agent box.** The ticket-loop's build subagents create isolated
   worktrees under `<repo>/.claude/worktrees/agent-*` plus local branches
   (`agent/<ticket>`, `worktree-agent-*`), and nothing in the agent tier ever deletes
   them. The prune policy exists only in the laptop-side `/worktree` skill
   (`worktree-reset.sh`). Observed on the nt box: ~2.5 GB of dead worktree checkouts
   (niptao 1.6 GB, paytunes 869 MB), 19–37 stale branches per clone, disk at 100%.
2. **No way to cut a release without a laptop.** `/release` (the base→prod promotion
   PR) requires an interactive session in the canonical checkout. Humans in the
   Telegram group should be able to trigger it.

## Part 1 — Runner sweep (the agent-tier prune policy)

New script **`skills/ticket-loop/sweep-worktrees.sh`**, the agent-tier twin of
`worktree-reset.sh --gc`. Standalone-callable (`sweep-worktrees.sh <repo-dir>`) so it
is testable and usable manually via `docker exec`.

Per repo dir, in order:

1. `git worktree prune` — clear metadata for already-deleted dirs.
2. **Remove loop-owned worktrees only:** every `.claude/worktrees/*` entry whose
   checked-out branch matches `agent/*` or `worktree-agent-*` (the loop's own naming) —
   `git worktree remove --force`, then `rm -rf` any orphan dir under
   `.claude/worktrees/` not registered as a worktree whose name matches `agent-*`.
   Worktrees on any other branch are left alone (a human's or another tool's).
   Safe because the sweep runs pre-pass under the singleton lock (no build can be in
   flight) and branches survive worktree removal — work is never lost.
3. **Delete merged local branches** matching `agent/*` or `worktree-agent-*` only:
   - **Ancestry check first:** `git merge-base --is-ancestor <ref> origin/<base>` →
     delete (`-D` after the explicit check; mirrors `worktree-reset.sh`).
   - **Squash-merge fallback, `agent/*` only:** ancestry fails for squash merges, and
     agent branches always have a PR — so if `gh pr list --head <branch> --state merged`
     (repo-scoped) returns a PR, the branch is deletable. `worktree-agent-*` harness
     branches never get PRs, so they get ancestry-only.
   - **Degradation:** no `gh`, no network, or the query errors → skip the fallback,
     ancestry-only, never guess. Unmerged branches always stay (refs, ~zero disk).
4. **No remote sweep.** GitHub auto-delete-on-merge owns remote branches; the box
   token keeps its minimal scope.

### Wiring (`cron-run.sh`)

Called right after the sitting-tree reset:

- always on `$DW_WORK_TREE`;
- in parent/manager mode, additionally on each immediate child dir that carries the
  **`.dw-agent-clone` marker** (the existing parent-mode guard — never a bare
  "has `.git`" heuristic).

Always-on policy — no config key, matching the reset itself. `TICKET_LOOP_NO_SWEEP=1`
env escape hatch for debugging. The `hooks.pre_pass` seam is untouched and still runs
after the sweep. Sweep failures are logged WARN and never abort the pass.

## Part 2 — Telegram `release` message class

### Classification (ticket-loop SKILL step-1 routing; parent SKILL routing table)

First line case-insensitive `release` or `release <repo>`, `ticket: null`.

- **Single-repo loop:** bare `release` → the sitting repo. `release <name>` must match
  this repo's name, else reply `unknown repo`.
- **Parent loop:** `release <child>` routes to that child's clone. Bare `release` →
  ask "which repo?" with the child list (same reply-routing pattern as `question:`).
  Handled **immediately in the message-drain phase** (cross-repo, like `question:`) —
  never deferred to the child's round-robin turn.
- **Auth:** group membership is the trust boundary — no allowlist, no confirmation
  round-trip (explicit decision). The flow only opens a PR; deploying stays the
  human's GitHub merge.

### Config gate (refuse-with-reason before any git action)

Requires **all** of: `repo.prod_branch`, `deploy.trigger`, `version.file`,
`version.scheme`, `version.changelog`. Any missing → reply
`🛑 <repo> isn't release-configured (missing <keys>)` and stop. (Supersets /release
safety rule 1, which the interactive skill enforces for the first two only.)

### Execution

Ack `🚀 Release requested for <repo> — cutting the release PR…`, then spawn one
**foreground, awaited subagent, no isolation worktree** (release must run in the
canonical clone on the base branch — exactly what the sitting tree / marker-verified
child clone is). The subagent follows the full `/release` contract:

1. **Full preflight** — on `repo.base_branch`, clean tree, `git fetch` +
   `git pull --ff-only`; any failure → abort + report, touch nothing.
2. **Resume detection** — if the base tip is already an unreleased version-bump commit
   (its tag exists but no open base→prod release PR), skip to step 5: a previously
   failed attempt left a durable, pushed bump — opening the PR completes it. This
   closes the partial-failure window (pushed bump + no PR).
3. Absorb hotfixes: merge `origin/<prod_branch>` into base; STOP on non-trivial
   conflicts (abort the merge first — see failure hygiene).
4. Version bump per `version.scheme`, regenerate changelog via `version.changelog`,
   single commit, tag `v<X.Y.Z>`, push commit + tag to base — **the one sanctioned
   exception** to the loop's "never push the base branch" baseline (same scoped
   carve-out `/release` documents), valid only inside a human-requested release flow.
5. Open the base→prod PR titled **`Release v<X.Y.Z> [agent]`** (the stable marker) —
   then **STOP. Never merge it.**
6. Reply `🚀 <repo> v<X.Y.Z> release PR opened: <url> — merging it deploys` + top
   changelog lines.

**Failure hygiene:** on any failure the subagent must leave the clone clean
(`git merge --abort` / `git reset --hard` as appropriate) and the loop reports what
failed and that re-sending `release` retries (resume detection makes retry safe).
Nothing may depend on local state surviving to the next pass — the runner's hard
reset would wipe it.

### Guardrail edit (ticket-loop + parent SKILL baselines)

"Never push the base or prod branch" gains the same scoped exception `/release`
already carries: the single version-bump commit + its tag, only inside a
human-requested release flow. Everything else stays forbidden (no force-push, never
merge the release PR, never push prod).

### Release babysit + announce (no new local state)

Identification is the marker, never inference: a release PR is
`--base <prod_branch>` **and** title matching `Release v* [agent]`. Hotfix or
human-made prod PRs never match.

- **Open + red CI** → ⚠️ line in the group (same style as agent-PR babysit).
- **Merged** → send `🎉 <repo> v<X.Y.Z> live`, then mark the PR itself with a
  `📣 announced` comment (state lives on GitHub — no `state.json` map, no new
  `dw-telegram` subcommand, no drift). Babysit skips merged release PRs that already
  carry the marker comment.
- **Digest:** pending release PRs get a 🚀 line.

### Instant announce via merge hook (optional, human-installed)

The babysit announce is poll-based — a merge between passes waits for the next pass.
For instant announcement the framework ships a **copyable GitHub Actions template**
(`dev-process/templates/release-announce.yml`): `on: pull_request` /
`types: [closed]`, gated on `merged == true`, base = the repo's prod branch, and
title matching `Release v* [agent]`. It sends the `🎉 <repo> v<X.Y.Z> live` Telegram
message (version parsed from the PR title; `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
as repo secrets) **and posts the same `📣 announced` marker comment** — so the loop's
babysit finds the marker and stays quiet. No coordination state; the loop remains the
fallback for repos without the hook or when the Action fails.

Per the framework baseline the agent never edits `.github/workflows/**` — a human
copies the template in, exactly like `dev-process/scripts/`.

## Testing

- **Sweep:** smoke test script beside `test_orchestrator_smoke.sh` — builds a temp
  repo with fake `agent/*` worktrees + merged/unmerged/squash-simulated branches +
  a non-loop worktree; asserts: merged gone, unmerged kept, non-loop worktree kept,
  orphan dirs removed, `TICKET_LOOP_NO_SWEEP=1` is a no-op. `gh` fallback covered via
  a stub `gh` on PATH.
- **Docs:** ticket-loop README message table, both SKILL.mds, and
  `dev-process/templates/release-announce.yml` (new, with install note);
  `python3 -m py_compile` where applicable (no Python changes expected in this
  design).

## Explicitly out of scope

- Laptop-side squash detection in `worktree-reset.sh` (stays parked in the
  2026-07-16 spec).
- Remote branch deletion from the box.
- Any auth/allowlist for the Telegram `release` trigger.
- Merging the release PR from anywhere but a human's GitHub click.
- Box-side one-time cleanup of the existing backlog (operational task, not framework
  code — the new sweep will catch most of it on first pass).
