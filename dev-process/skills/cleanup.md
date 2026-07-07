# Skill: cleanup — session closer (feature→dev PR)

> Claude Code: save as `.claude/skills/cleanup/SKILL.md`. Placeholders:
> `[TEST COMMAND]` (e.g. `scripts/test.sh <pkg>`), `[LINT COMMAND]`,
> `[TRACKER]`. Pairs with `scripts/ship-preflight.sh`.

End-of-session ship: commit anything outstanding, push the branch, open a PR **into
`dev`** (the integration trunk — merging it does NOT deploy), and close out the
tickets the session completed. Its job is to **finish** the session's work, not redo
it. Invoking it is the human's authorization to push and open the PR.

**Modes.** Default is FAST: trust the session's commit-as-you-go and earlier green
tests; CI re-runs the full suite on the PR (the authoritative gate). `--full` adds a
mechanical hygiene scan of changed files and re-runs the diff's tests regardless.
Hotfix branches (based on `main`): pass `--base main` to the preflight calls and
target the PR at `main`.

## Step 1: Assess (one call)

```bash
scripts/ship-preflight.sh assess          # add --base main for a hotfix branch
```
Prints branch, dirty status, diff stat, unpushed commits, and a `COUNTS` line. If
`NOTHING_TO_SHIP=1`, say so and stop.

## Step 2: Hygiene pass — `--full` only

Skip by default (and always for docs-only diffs). With `--full`: run [LINT COMMAND]
with auto-fix on the changed files, strip debug leftovers, fold fixes into the
relevant commit. Flag (don't fix): TODO/FIXME leftovers, anything that looks like a
hardcoded secret, obviously-dead code in the diff.

## Step 3: Commit messages ARE the changelog

Generate the changelog from commits — don't hand-edit a CHANGELOG file. So the real
work here: every commit must be a good changelog line — conventional
`type(scope): subject` with a body explaining the *why*. Reword vague not-yet-pushed
subjects now (amend).

## Step 4: Commit remaining changes

Stage the relevant files (never `.env`/secrets), write a conventional message from
the diff, commit.

## Step 5: Tests — trust the session by default

- Already ran the relevant tests green this session, nothing changed since → skip,
  and say so ("tests already green this session; CI re-runs the full suite").
- Docs-only → skip.
- Unvalidated runtime changes or `--full` → run the **narrowest** relevant scope:
  `[TEST COMMAND]`. Never push code you have reason to believe is broken — a red
  test means STOP and fix.

## Step 6: Sync + push + open the PR

```bash
scripts/ship-preflight.sh sync-push       # add --base main for a hotfix
```
Refuses on a dirty tree; stops with the conflicted-file list on merge conflicts.
Then open or update the PR (idempotent — never a second PR for one branch):
- No open PR → `gh pr create --base dev --head <branch>` with a real title, a
  `## Summary` grouped by theme, a `## Test scope` line, and a test-plan checklist.
  **Always a real PR URL — never just a compare link.**
- Open PR exists → `gh pr edit --body` with the refreshed body.

## Step 7: Close out completed tickets

Gather ticket IDs from the branch name and commit messages. For each: read the
commits to decide whether it actually shipped in this branch (don't trust the branch
name alone). Completed → move to Done in [TRACKER]. Partially done → leave In
Progress and say what's left. Never auto-close decision/gated-labelled tickets.

## Step 8: Session handoff (last output)

- **Shipped** — 2-4 bullets of what changed + why it mattered; PR URL; test posture;
  tickets closed.
- **Carry into next session** — the non-obvious context not in the diff: decisions +
  rationale, deliberate deferrals, gotchas hit.
- **Natural next steps** — 2-3 concrete follow-ons (real ticket IDs). Suggestions,
  not commitments.

Close with the reminder: merging this PR lands on `dev` and does **not** deploy —
prod ships only when `dev→main` is promoted via /release.
