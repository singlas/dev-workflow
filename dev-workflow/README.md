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
python3 dev-workflow/validate.py dev-workflow.yml     # -> OK: dev-workflow.yml
```

Shell callers read individual values by dotted path:

```
python3 dev-workflow/dw-config.py dev-workflow.yml tracker.team        # -> Acme
python3 dev-workflow/dw-config.py dev-workflow.yml build.model sonnet  # value or default
```

The tracker is a swappable adapter — skills speak canonical verbs
(`list_actionable`, `move`, `label`, …) that map onto a provider (Linear
today). All state/label names come from `tracker.roles`, never hardcoded. See
[`tracker-adapters.md`](tracker-adapters.md).

## Distribution

Two shapes, one framework:

- **Docker runner** — for the autonomous loop. The image bakes the runner +
  plugin at `/opt/dev-workflow` and runs on a timer against a mounted work
  tree. Setup: [`../skills/ticket-loop/docker/README.md`](../skills/ticket-loop/docker/README.md).
- **Claude Code plugin** — for the interactive skills (`standup`, `cleanup`,
  `release`, and `ticket-loop` when driven by hand). Install it with
  `claude plugin install` (plugin name `dev-workflow`), or point Claude Code
  at this checkout with `--plugin-dir`.

## Files here

| File | What it is |
|---|---|
| [dev-workflow.example.yml](dev-workflow.example.yml) | Annotated full config example (generic values) |
| [validate.py](validate.py) | Schema + tighten-only validator (PyYAML) |
| [dw-config.py](dw-config.py) | Dotted-path config reader for shell callers |
| [test_validate.py](test_validate.py) | `unittest` suite for the validator |
| [tracker-adapters.md](tracker-adapters.md) | Canonical verbs → provider mapping (Linear impl) |
