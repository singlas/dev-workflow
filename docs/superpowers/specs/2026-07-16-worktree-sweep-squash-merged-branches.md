# Future work: prune squash-merged branches in the `/worktree` sweep

**Status:** parked / not scheduled. User story only — no approach chosen, no implementation.
**Captured:** 2026-07-16

## User story

**As** a developer whose repo squash-merges PRs,
**I want** `/worktree` (RESET and `--gc`) to prune branches whose PR was squash-merged into the trunk,
**so that** merged branches don't pile up locally and remotely, and I don't have to delete them by hand.

## Background / why today's behavior falls short

- The sweep lives in `dev-process/scripts/worktree-reset.sh` (`sweep_merged_local()` / `sweep_merged_remote()`).
- "Merged" is detected purely by commit ancestry: `git merge-base --is-ancestor <ref> origin/<trunk>`.
- A squash merge lands a **new-SHA** commit on the trunk, so the branch tip is never an ancestor. The ancestry check (and `git branch --merged`) silently skip every squash-merged branch — so squash-merging repos get **no auto-prune at all**.

## Acceptance criteria

1. A branch whose PR was squash-merged into the trunk is swept (local **and** remote), the same way a true-merged branch is today.
2. No unmerged branch is ever deleted — a branch with commits not yet in the trunk must be preserved. Long-lived branches (trunk/prod/master) stay excluded.
3. `--keep-remote` still skips remote deletion; `--gc` still works standalone.
4. Behavior is **safe when PR/merge metadata is unavailable** (offline, no `gh`, non-GitHub host): degrade gracefully, never mis-delete.

## Out of scope

- No implementation, no chosen approach. Open questions below are questions, not decisions.

## Open questions

1. **How to recognize a squash merge reliably?** Candidate signals, each with trade-offs — none decided:
   - Ask the host: `gh pr list --state merged --head <branch>` (or the PR's `mergedAt`/`state`). Accurate, but GitHub-only and needs network + `gh` auth.
   - Content-equivalence: does the branch's squashed diff already exist in the trunk (e.g. `git cherry`, or comparing tree/patch-id against trunk)? Host-agnostic and works offline, but fuzzier and can misjudge rebases/partial merges.
   - Rely on branch-name → PR convention. Cheap, but brittle.
2. **What's the safe fallback when metadata is unavailable?** Presumably fall back to today's ancestry-only check and skip squash-detection — prune nothing extra rather than risk a wrong delete. Confirm that's the intended degradation.
3. **Does squash-detection gate on the PR being merged specifically**, vs. merely "diff already present in trunk"? (A closed-unmerged PR, or an abandoned branch whose changes happened to land via another PR, shouldn't necessarily be treated the same.)
4. **Local vs. remote asymmetry:** should squash-detection apply identically to both `sweep_merged_local` and `sweep_merged_remote`, or is remote deletion held to a stricter bar (e.g. require host confirmation of a merged PR, never content-equivalence)?
5. **Scope of "trunk":** is it always the single configured integration branch from `dev-workflow.yml`, or should a branch squashed into `prod` (bypassing base) also count as merged?
