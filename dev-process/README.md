# AI-Team Dev Process

A complete development process for a small team (or solo founder) working with AI coding
agents: a two-branch model where deploys are always deliberate, parallel work in git
worktrees, session skills that open/close the day, and an autonomous "AI employee" loop
that works a ticket queue, asks questions in chat, and submits PRs for human review.

Battle-tested on a production Django SaaS run by one founder + Claude Code. Everything
here is tool-agnostic in shape; the skill files are written for Claude Code
(`.claude/skills/*/SKILL.md`) but port to any agent harness that supports reusable
instructions.

```
dev-process/
├── README.md                    # this playbook
├── scripts/
│   ├── worktree-reset.sh        # fresh feature branch per worktree slot + garbage collection
│   └── ship-preflight.sh        # the deterministic git dance behind "wrap up and PR"
└── skills/
    ├── standup.md               # pointer stub → ../skills/standup/ (real plugin skill)
    ├── cleanup.md               # pointer stub → ../skills/cleanup/ (real plugin skill)
    └── release.md               # pointer stub → ../skills/release/ (real plugin skill)
```

The three session skills are now real, installable plugin skills at the repo root —
[`skills/standup/`](../skills/standup/), [`skills/cleanup/`](../skills/cleanup/),
[`skills/release/`](../skills/release/) — config-driven off `dev-workflow.yml` (no
`[PLACEHOLDER]` markers to hand-edit). The stubs above just point to them. The
autonomous agent employee lives alongside them:
[`../skills/ticket-loop/`](../skills/ticket-loop/) (SKILL.md + Telegram bridge +
env example) — section 5 below explains how it fits this process.

---

## 1. The branch model: deploys are deliberate

Two long-lived branches. The invariant: **`main` always equals exactly what's in prod.**

| Branch | Role | Deploys? |
|---|---|---|
| `dev` | Integration trunk. Feature branches start here and PR back here. | No — CI runs lint + tests only. |
| `main` | Prod mirror. Advances **only** via a `dev→main` PR (or a hotfix PR). | **Yes** — a push to `main` deploys. |

Why this matters with AI agents: agents open a lot of PRs. If merging a feature PR
deployed to prod, every merge would be a production event. With this model, merges to
`dev` are cheap and frequent; the deploy is one deliberate `dev→main` promotion you make
when a batch is ready.

**Hotfixes:** urgent prod fix branches off `main`, PRs straight to `main` (deploys),
then immediately back-merge `main→dev` so the next promotion doesn't revert it.

### CI shape (GitHub Actions)

- Any PR or push to `dev` → lint + full test suite. **No deploy.**
- Push to `main` (a merged `dev→main`/hotfix PR) → same gate, then the deploy job
  (gated with `if: github.ref == 'refs/heads/main'`).

CI is the authoritative test gate. Local test runs exist to catch failures before the
round-trip, not to replace CI.

---

## 2. One-time GitHub setup (requires a paid plan for private repos)

1. **Create `dev` from `main`** and make it the **default branch** (Settings → General),
   so feature PRs target it automatically:
   ```bash
   git push origin origin/main:refs/heads/dev
   gh api -X PATCH repos/{owner}/{repo} -f default_branch=dev
   ```
2. **Auto-delete head branches on merge** — merged PR branches vanish from origin on
   their own:
   ```bash
   gh api -X PATCH repos/{owner}/{repo} -F delete_branch_on_merge=true
   ```
3. **Protect `main` with a ruleset** — since a push to `main` deploys, make an
   accidental direct push impossible. Require a PR (0 approvals keeps solo merges
   possible), require the CI checks, block force-pushes and deletion, no bypass actors
   (applies to admins too — break-glass is disabling the ruleset in the UI):
   ```bash
   gh api -X POST repos/{owner}/{repo}/rulesets --input - <<'JSON'
   {
     "name": "protect-main",
     "target": "branch",
     "enforcement": "active",
     "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
     "rules": [
       { "type": "deletion" },
       { "type": "non_fast_forward" },
       { "type": "pull_request", "parameters": {
           "required_approving_review_count": 0,
           "dismiss_stale_reviews_on_push": false,
           "require_code_owner_review": false,
           "require_last_push_approval": false,
           "required_review_thread_resolution": false } },
       { "type": "required_status_checks", "parameters": {
           "strict_required_status_checks_policy": false,
           "required_status_checks": [
             { "context": "lint" },
             { "context": "test" } ] } }
     ],
     "bypass_actors": []
   }
   JSON
   ```
   The `context` values must match your CI **job names** exactly — verify on the first
   PR after enabling (if the merge button waits on a check that "never ran", the name
   is wrong).

---

## 3. Worktrees: parallel agent sessions that don't collide

One canonical checkout (stays on `dev`) plus a handful of **worktree slots** — fixed
directories (`../PROJECT-worktrees/feature-a` … `feature-d`), each hosting one agent
session at a time. Worktrees share one `.git`, so:

- **Rule: each session works on the branch its worktree is already on, and never
  switches branches** — a branch switch in one worktree yanks state out from under the
  others.
- **Fresh branch per feature, never reused:** `scripts/worktree-reset.sh` mints an
  auto-numbered branch (`feature-a-7`) at the *latest* `origin/dev`. Reusing one branch
  name per slot causes stale-base divergence and (in Django/Rails) migration-number
  collisions; a fresh branch each time avoids both, and lets the previous feature's PR
  stay open while you start the next.
- **Shared state via symlinks:** gitignored per-machine files (`.env`, local scratch,
  agent permission settings) are symlinked from the canonical repo into each worktree,
  driven by a tracked `.worktree-shared` manifest. Build state (venv, node_modules) is
  per-worktree on purpose.
- **Garbage collection:** every reset also sweeps *dead worktrees* — branch fully merged
  into `origin/dev`, no tracked changes, idle >3 days — and deletes merged local+remote
  branches. `worktree-reset.sh --gc` runs the sweep standalone. Without this, ad-hoc and
  agent-created worktrees accumulate forever, pinning their merged branches.

Both scripts in `scripts/` are ready to copy; `worktree-reset.sh` has one EDIT-ME (your
dependency install command).

---

## 4. The daily loop (the three session skills)

```
/standup ──► pick work off the board (read-only orientation)
    │
scripts/worktree-reset.sh ──► fresh branch off origin/dev in a slot
    │
build ──► commit after every meaningful unit; test what you change
    │
/cleanup ──► commit what's left, sync+push, PR INTO dev, close tickets   (no deploy)
    │
/release ──► from the canonical repo on dev: version bump, changelog, tag,
    │         open the dev→main PR  (CI is the test gate)
    ▼
merge dev→main ──► DEPLOY   (always the human's click, never the agent's)
```

Principles that make this work with agents:

- **Commit as you go; the closer trusts the session.** `/cleanup` is fast by default —
  it finishes the session (commit, push, PR, tickets) rather than re-auditing it. CI
  re-runs the full suite on every PR anyway. A `--full` flag exists for messy sessions.
- **The changelog is generated from commits, not hand-edited.** Enforce conventional
  commits (`type(scope): subject` + a why-body); a small script groups them into a
  changelog view per version. Nothing to merge-conflict, nothing to forget.
- **Ticket state moves as work moves** — start → In Progress, PR merged → Done — done by
  the skills, not remembered by the human.
- **The agent never merges to prod.** Opening the `dev→main` PR is scripted; merging it
  is the human's explicit action, every time.

The three session skills are real plugin skills ([`../skills/standup/`](../skills/standup/),
[`cleanup/`](../skills/cleanup/), [`release/`](../skills/release/)) driven by
`dev-workflow.yml` — install the `dev-workflow` plugin or copy the folders into
`.claude/skills/`, set the config once, and there's nothing per-skill to hand-edit.

---

## 5. The AI employee: an autonomous ticket loop

[`../skills/ticket-loop/`](../skills/ticket-loop/) is the full drop-in package —
the SKILL.md, a stdlib-Python Telegram bridge, an env example, and its own
quickstart README. The shape:

1. **Queue:** tickets in your tracker labeled `agent` are the agent's inbox. The label
   is only ever applied by a human, in the team chat group — the agent never
   self-assigns.
2. **Questions:** if a ticket is ambiguous, the agent posts ONE batched question to the
   team chat (we use a Telegram group + a ~150-line bot poller), mirrors the Q&A onto
   the ticket, labels it `agent-blocked`, and moves on. Answers unblock it on the next
   pass.
3. **Build:** each ticket is implemented by a subagent in an isolated worktree, on a
   branch like `agent/tik-123`, tests + lint run, then a PR into `dev` (title tagged
   `[agent]`).
4. **Babysit (the back half — what makes it an employee, not a fire-and-forget bot):**
   every pass, before new work, the agent sweeps its open PRs:
   - **merged** → move the ticket to Done, comment, notify the group;
   - **review comments or red CI** → spawn a revision subagent that addresses each
     comment, pushes (never force), and replies to the reviewer;
   - **merge conflict with dev** → heal by merging dev into the branch (never rebase —
     rebases need force-pushes).
5. **Daily digest:** once a day (and on demand), one chat message: merged yesterday /
   PRs awaiting your review (with age) / tickets blocked on unanswered questions (with a
   single >24h reminder) / what's queued. Employees report in; you shouldn't have to ask.
6. **Security guardrails** (non-negotiable, included in the template): ticket text and
   chat messages are *data, not instructions* — prompt-injection defense; scope limited
   to the repo; never push `main`/`dev` or force-push; no secrets in code, logs, or PR
   text; tooling/dependency changes flagged to a human; oversized diffs stopped and
   escalated.

### Maturity ladder (adopt in this order)

| Stage | What | Cost |
|---|---|---|
| 1 | Run the loop manually in a dedicated worktree session | zero infra |
| 2 | PR babysitting + close-on-merge + daily digest (in the template already) | zero infra |
| 3 | Cron a headless single pass every ~30 min + a morning `--report` pass | one cron/launchd entry |
| 4 | Dedicated identity: a GitHub machine user (write-only PAT) + a tracker agent user, so PRs/comments come *from the employee* and you can formally review them | two accounts |

---

## 6. Hygiene rules that keep it honest

- Push `dev` immediately after committing directly to it — it's the shared trunk; an
  unpushed local commit diverges the moment a PR merges upstream.
- Run `worktree-reset.sh --gc` (or just reset a slot) regularly; add a hygiene line to
  your standup brief: unpushed trunk commits, agent PRs awaiting review, dead worktrees.
- Keep docs describing the process in sync with the skills that implement it — when a
  skill gets leaner, update the doc the same commit. Drift here is how process rot
  starts.
