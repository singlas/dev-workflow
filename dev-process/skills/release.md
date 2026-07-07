# Skill: release — the dev→main promotion that DEPLOYS

> Claude Code: save as `.claude/skills/release/SKILL.md`. Placeholders:
> `[TEST COMMAND]` (full suite), `[TEAM CHANNEL]` (Telegram/Slack/WhatsApp group),
> `[VERSION FILE]` (e.g. a root `VERSION` file).

The deliberate promotion of accumulated `dev` work to `main` — the merge that deploys
to prod. Treat it with care: the `dev→main` PR opened here ships the moment it's
merged. **Run it in the canonical repo, on `dev`** — not in a feature worktree (the
version bump is a commit on `dev`).

**Modes.** Default is lean: CI is the authoritative test gate (it runs the full suite
on the `dev→main` PR and again on the `main` push), so no local full run. Pass
`--full` to run [TEST COMMAND] locally first when the batch is risky (wide migration,
settings change). Ticket state is NOT handled here — /cleanup owns it at the
feature-PR stage.

**Single-PR fast path (automatic).** First check open feature→`dev` PRs
(`gh pr list --base dev --state open`). Exactly ONE with green CI → merge it into
`dev`, then immediately release — one motion. Say the fast path was taken. ZERO open
PRs → plain release of what's on `dev`. 2+ → ask which should ride along; never
auto-merge a batch. Failing/running CI on the pending PR → stop. A fast-path release
is always a minor/patch bump, never major.

## Preflight — you must be in the right place
1. Canonical repo, not a worktree (`git rev-parse --show-toplevel` equals the dir of
   `git rev-parse --git-common-dir`). If not, STOP.
2. Branch is `dev`. If not, STOP — don't switch branches for the user.
3. `git fetch origin --prune` then `git pull --ff-only origin dev`. Not
   fast-forwardable → STOP and surface why.

## Step 1 — absorb hotfixes (keep main an ancestor of dev)
If `main` has commits `dev` doesn't, promoting would *revert* them:
```bash
git merge origin/main --no-edit
```
Clean merge → fine. Conflicts → resolve the simple ones, STOP on anything non-trivial.

## Step 2 — tests: CI is the gate (`--full` opts into a local run)
With `--full`, run [TEST COMMAND]; red → STOP, never open a release PR on a red
suite. Without it, note "CI is the test gate; no local full run" in the summary.

## Step 3 — pick the new version
Read [VERSION FILE], review what's shipping (grouped commit log since `main`).
Propose the bump from the change shape (features → feature segment; fixes only →
patch), **show it and let the human confirm/override**, then write it.

## Step 4 — commit, push dev, tag, open the dev→main PR
1. `git add [VERSION FILE] && git commit -m "release: VERSION <new> — <one-line theme>"`
2. `git push origin dev` (does not deploy — only main does).
3. Tag: `git tag -a v<new> <bump-sha> -m "Release <new> — <theme>"` then push the tag.
4. Open the PR — a real PR, never a compare link:
   ```bash
   gh pr create --base main --head dev --title "Release <new>" --body "<body>"
   ```
   Body: `## Summary` grouped from `git log origin/main..dev --oneline`, the new
   version, a `## Tests` line, and a `## Deploy` note that **merging this PR deploys
   to prod**.

## Step 5 — announce (after the human merges)
Merging is the human's call. Once merged, post to [TEAM CHANNEL]:
`🚀 Released v<new> — <theme>` + 3-6 highlight bullets written for the people reading
the group (what changed *for them*, not raw commit subjects).

## Never
- Run from a feature worktree, or on any branch but `dev`.
- Open a release PR on a failing suite.
- **Merge the `dev→main` PR yourself** — merging deploys; that's the human's click.
- Hand-edit a changelog file — it's generated from commits.
