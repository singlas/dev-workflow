# dev-workflow — CI for ticket work

`dev-workflow` is the framework that turns a team's dev process — the
`standup` / `cleanup` / `release` skills and the autonomous **ticket-loop**
agent — into a codebase-agnostic package you configure per repo with a single
`dev-workflow.yml`.

**The mental model: CI, but for ticket work.** CI is a generic runner (GitHub
Actions) that reads a per-repo file (`.github/workflows/*.yml`) and runs your
tests inside guardrails you can tighten but not escape. `dev-workflow` is the
same shape for *doing* the work rather than checking it: a generic runner +
plugin reads a per-repo `dev-workflow.yml` and works your board — picking up
tickets, asking questions in team chat, opening one reviewable PR each — inside
framework guardrails a repo can tighten but never loosen.

## Three zones

Everything splits into three zones. The framework is generic and shared; the
target repo owns only its config; secrets and auth are injected at runtime and
live nowhere in git.

| Zone | Owns | Lives in |
|---|---|---|
| **Framework** (generic) | The plugin (skills), the runner scripts, the Docker image, the validator. Identical across every repo. | This repo — `.claude-plugin/` + `skills/` + `dev-workflow/`, and the baked container root `/opt/dev-workflow` (root-owned). |
| **Target-repo config** | One `dev-workflow.yml` + the repo's own `CLAUDE.md`. Chooses branch model, tracker team/roles, test/lint commands, tightened guardrails. | The target repo root (tenant #1 is the repo you point it at). |
| **Injected** | Secrets (`agent.env`), Claude auth (`~/.claude`), the loop's `state.json`. Never in git. | A mounted volume / the environment at runtime. |

## Two boundary rules

These two rules are non-negotiable — they are what make the framework safe to
point at any repo.

1. **Config can only tighten, never loosen.** The baseline guardrails are
   framework-side constants. A `dev-workflow.yml` may *add* protected paths or
   *lower* a diff budget, but it can never switch a baseline off or raise a
   ceiling. `validate.py` enforces the ceilings; the runner enforces the
   baseline. (`guardrails.diff_budget.max_lines ≤ 400`, `max_files ≤ 15`,
   `build.cap_per_pass ≤ 2`.)
2. **The runner lives outside the mounted work tree.** In the container the
   runner + plugin are baked root-owned at `/opt/dev-workflow`; the target
   repo checkout is the mounted volume at `/home/agent`. A build subagent runs
   as a non-root user against the work tree and therefore *physically cannot*
   edit the framework driving it.

## Baseline guardrails (framework-side, non-overridable)

- Never push the base or prod branch directly — PRs only. No force-push.
- Never read secrets: `.env*`, `*.key`, `*.pem`, `credentials.json`,
  `~/.claude/**`, `.claude/settings*`.
- Never edit the framework — the plugin, the runner scripts, the loop's own
  `SKILL.md`.
- Never edit the repo's `dev-workflow.yml` — the agent must never edit its own
  leash (it defines `off_limits` and the diff budget); config changes need a human.
- Deploys only via the repo's CI-gated promotion. `.github/workflows/**` is
  off-limits.

A repo's `guardrails.off_limits` **adds** to the secret/path list above; it
never shrinks it.

## Config contract

`dev-workflow.yml` lives at the *target repo root*. Copy
[`dev-workflow.example.yml`](dev-workflow.example.yml), edit the values, and
validate:

```
uv run dev-workflow/validate.py dev-workflow.yml     # -> OK: dev-workflow.yml
```

Shell callers read individual values by dotted path:

```
uv run dev-workflow/dw-config.py dev-workflow.yml tracker.team        # -> Acme
uv run dev-workflow/dw-config.py dev-workflow.yml build.model sonnet  # value or default
```

The tracker is a swappable adapter — skills speak canonical verbs
(`list_actionable`, `move`, `label`, …) that map onto a provider (Linear
today). All state/label names come from `tracker.roles`, never hardcoded. See
[`tracker-adapters.md`](tracker-adapters.md).

**Optional `blog:` section.** Set it to opt the `cleanup` skill into an offer to
turn a sharp session learning into one local draft — off unless present:

```
blog:
  skill: blog-from-session      # repo-local skill to invoke (falls back to the bundled blog-from-session)
  posts_dir: docs/blog          # where the bundled skill writes drafts (default: docs/blog/)
  publish: ""                   # optional publish command; cleanup NEVER runs it unprompted
```

`skill`/`posts_dir`/`publish` are each optional (validated as non-empty strings
when present). With no `blog:` section, `cleanup` never mentions a post; even with
it, the skill only ever writes ONE draft file locally — it never publishes,
commits, or pushes. See [`../skills/blog-from-session/`](../skills/blog-from-session/).

## Distribution — three tiers, one framework

The framework ships as one plugin with three adoption tiers. A repo takes only as
much as it wants; each tier builds on the one before.

### v1 — Local developer (default, every install)

The interactive session skills, working locally. Install the plugin
(`claude plugin marketplace add singlas/dev-workflow` once, then
`claude plugin install dev-workflow` — or `--plugin-dir <checkout>`), then:

- Run **`/setup`** to write a validated `dev-workflow.yml` (prereq checks +
  interview), or copy [`dev-workflow.example.yml`](dev-workflow.example.yml) by hand.
- Work the day with **`/standup`** → **`/cleanup`** → **`/release`** (plus
  **`/blog-from-session`**). The branch model is worktree-based — the playbook +
  ready-to-copy scripts are in [`../dev-process/README.md`](../dev-process/README.md).
- A **SessionStart hook** auto-orients any session opened in a configured repo
  (and stays silent everywhere else).

### v2 — Local agent (opt-in, OFF by default)

A local autonomous agent — the `ticket-loop` skill + its launchd/cron installer —
working the queue on your own machine, one PR per ticket. **Gated by
`agent.enabled: true`** in `dev-workflow.yml`: absent or false, and both
`/ticket-loop` (interactively) and [`../skills/ticket-loop/install-cron.sh`](../skills/ticket-loop/install-cron.sh)
refuse with an opt-in message. Supply the loop's env
([`../skills/ticket-loop/env.example`](../skills/ticket-loop/env.example)) and
install the schedule. `agent.enabled` is a feature switch, not a guardrail — it
never loosens a ceiling.

### v3 — Remote runner (repo-level, separate — not a plugin install)

The Docker image + multi-project orchestrator, running unattended on a server
against mounted work trees. The image bakes the runner + plugin root-owned at
`/opt/dev-workflow` (boundary rule 2). This tier is **not gated on
`agent.enabled`** (a live deployment predates the key) and is **not** set up via
the plugin. Follow the docs in order:

1. **One repo, in Docker** — build the image, mount a work tree, set the timer:
   [`../skills/ticket-loop/docker/README.md`](../skills/ticket-loop/docker/README.md).
2. **Many repos** — the round-robin orchestrator over the same image:
   [`../skills/ticket-loop/orchestrator/README.md`](../skills/ticket-loop/orchestrator/README.md).

## Files here

| File | What it is |
|---|---|
| [dev-workflow.example.yml](dev-workflow.example.yml) | Annotated full config example (generic values) |
| [validate.py](validate.py) | Schema + tighten-only validator (PyYAML) |
| [dw-config.py](dw-config.py) | Dotted-path config reader for shell callers |
| [dw-board.py](dw-board.py) | Framework board tool — `snapshot` renders the board views, `prune` reports (or, if opted in, trashes) old Done/Canceled issues, `import` bulk-creates issues from a JSON holding file (`<board.views>/import.json`; dry-run unless `--yes`). Reads `tracker.team` + `board.*` from config; `LINEAR_API_KEY` from the env only |
| [test_validate.py](test_validate.py) | `unittest` suite for the validator |
| [tracker-adapters.md](tracker-adapters.md) | Canonical verbs → provider mapping (Linear impl) |
