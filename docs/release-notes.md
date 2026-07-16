# Release notes

## v0.6.1

**Ops-channel accuracy: real usage + limit≠auth.** Two fixes surfaced during a
shared-token-pool exhaustion across a multi-tenant orchestrator box. (1) The daily
usage digest read "in 170" because it summed only `input_tokens`/`output_tokens`
and ignored `cache_read`/`cache_creation` — the bulk of a cached agent's input.
It now reports the real input total including cache (e.g. "in 4.4M (cache 4.4M)")
with M-scale formatting. (2) When the shared token pool ran out, every roster
project errored at once and the orchestrator escalated "shared-auth failure
(expired token)" — an alarming, wrong diagnosis that sent people chasing a
credential problem. A session-limit hit and an expired token both error everyone,
but a limit-hit leaves `limit=true` in the tenant's latest `usage.jsonl` while an
auth failure writes no usage envelope; `orch.py` now discriminates and sends
"shared SESSION LIMIT hit … auto-resume once the pool resets" instead.

## v0.6.0

**Passive intake parking-lot for the parent loop.** A new optional
`tracker.intake_project` on a parent config gives `ticket-loop-parent` a durable,
human-visible home for reported work that isn't (or never will be) agent-built.
An untagged report in the shared Telegram group is *captured* as a real Linear
ticket in the intake Project (no queue label, one mutation, acked to the group),
and a projectless ticket the agent trips over is *parked* there instead of
dead-ended — both surface in the digest for a human to triage. Triage stays a
human act: move a ticket into a `repos:` project and green-light it to make it
agent work, or leave it to keep it human-owned. The agent never builds an intake
ticket; build stays gated by the queue label, and the intake Project is asserted
out of `repos:` in the validator so an intake ticket can never be auto-built.
Three durable write-safety points live in the parent's `state.json`
(`captured_reports` message→ticket dedup, park-before-move re-read, green-light
reconcile-to-terminal-state), and digest sections are keyed by project not label
so a stray queue label can't double-count. Purely additive: an unset
`intake_project` behaves exactly as before (ask-and-stash for a fresh report,
flag-and-refuse for a projectless/unmapped ticket).

## v0.5.3

**Parent orchestration: one product, many repos, one board, one group.** A new
`ticket-loop-parent` skill runs a whole multi-repo product as a single roster
entry — one Linear team, one Telegram bot + group — that round-robins its child
repos: each pass drains and routes the shared group globally, then works ONE child
(babysit its PRs + build its next ticket via a subagent in that child's clone).
Releases stay repo-level; the parent checkout is never reset; child clones and
their state stay isolated. The single-repo `/ticket-loop` is untouched and
config-selects between them.

Built spec-first (`docs/superpowers/specs/2026-07-13-parent-orchestration-*`) with
a Phase 0 GO/NO-GO prototype and six Codex review passes.

### Added
- **`ticket-loop-parent` skill** — the management plane (routing, questions,
  digest, scout, PR-babysitting) that dispatches every build as a subagent into
  the resolved child clone.
- **Per-entry mode selection** — roster `skill:` and `manager:` (overriding a
  repo's `agent.skill` / `agent.manager`) → `DW_SKILL` / `DW_MANAGER`. **Manager
  mode** stops the runner from `git reset --hard`-ing a parent checkout.
- **`repos:` config** — the parent's project→child-clone routing table, with
  duplicate-project/path and no-`tracker.project`-on-a-parent validation.
- **`DEFAULT_CLAUDE_CODE_OAUTH_TOKEN`** in `orch.env` — a common Claude token for
  every pass, overridden by a project's own `CLAUDE_CODE_OAUTH_TOKEN` (a separate
  account / session-limit pool).
- **Telegram bridge routing** — `send --project` / `--context`; `poll` emits
  `project` + `context`, so a reply routes to the right repo without a tracker
  read and a "which project?" clarifier completes in one reply.

### Fixed
- A parent pass that exits 0 without an `outcome.json` (config-read failure) now
  classifies as **error**, not a fake idle `dry` — a broken deploy escalates.
- `agent.skill` / roster `skill:` must be a **bare name** (a `:` value would
  double-prefix to `/dev-workflow:dev-workflow:…`).
- Manager-mode boolean coercion handled dw-config's capitalized `True`/`False`
  (a repo `agent.manager: true` was silently ignored, resetting the parent).

## v0.5.2

**Completes `tracker.project` in the runtime contracts (Codex-caught).** v0.5.1
scoped the pre-check (`queue-count.py`) by Linear Project but left the SKILL.md
contracts that drive the actual passes team-wide — so on a shared team a pass
could pick up a sibling repo's ticket the pre-check never counted, and
`create_ticket` could drop new tickets outside the project slice (`queue_count`
must match `list_actionable`; it didn't).

- `ticket-loop`: loads `tracker.project`; `list_actionable` and `create_ticket`
  (report + flag paths) now scope to the Project when set.
- `standup`: the board-snapshot fallback's `list_actionable` scopes to the
  Project too, so a shared-team brief doesn't surface other repos' tickets.

## v0.5.1

**Multi-repo tracking: one Linear team, one Project per repo.** A new optional
`tracker.project` in `dev-workflow.yml` scopes a repo to a single Linear Project
inside a team shared across repos — a multi-repo product (e.g. a backend split
across services) or one personal team spanning several hobby repos. Each repo
works only its own slice of the shared board; omit the field and everything is
team-only exactly as before.

- Every read/create verb (`queue_count`, `list_actionable`, `create_ticket`)
  additionally filters/sets the Linear Project when `tracker.project` is set.
- Issue **identifiers stay team-scoped** — all repos in the team share its key
  prefix; the Project field, not the key, distinguishes the repo. (Distinct
  prefixes still mean distinct teams — that's the one-team-per-repo model.)
- Pure tracker-layer: works for a plain developer running the interactive skills
  in one repo of a shared team — no Docker or orchestrator required.
- `validate.py` type-checks the field; `tracker-adapters.md` and the example
  config document it.

## v0.5.0

**Tiered install + the multi-project orchestrator.** The plugin now presents three
tiers in one install, and the autonomous loop grew a round-robin orchestrator for
running many repos on one box.

### Repo: the framework is the product
- The legacy copy-paste prompt collections moved from the repo root into
  **`extras/`** (with `workflows/` renamed `extras/handover/`), indexed by their
  own `extras/README.md`. The root README is now framework-only: pitch → tiers →
  quickstart → skills → architecture, plus a 5-line Extras pointer.
- Added the **MIT `LICENSE`** file (README already claimed MIT) and declared it in
  `plugin.json`.
- Install docs everywhere now show the full two-step flow:
  `claude plugin marketplace add singlas/dev-workflow` →
  `claude plugin install dev-workflow`.

### Tiered install (v1 / v2 / v3)
- **v1 — Local developer (default).** Everything works out of the box after
  `claude plugin install`: the session skills + a per-repo `dev-workflow.yml`.
- **v2 — Local agent (opt-in, OFF by default).** The `ticket-loop` skill + its
  launchd/cron installer are now gated by a new **`agent.enabled: true`** key.
  Absent/false → `/ticket-loop` (interactively) and `install-cron.sh` refuse with a
  clear opt-in message. It is a feature switch, deliberately independent of the
  tighten-only ceilings; the validator type-checks it (absent/true/false valid).
  **The v3 Docker/orchestrator path is NOT gated on this key** — production
  deployments predate it. The gate hangs off the interactive skill preflight (which
  the headless runner skips via `TICKET_LOOP_LOCK_HELD`) and `install-cron.sh` only,
  never `cron-run.sh`.
- **v3 — Remote runner (repo-level, separate).** The Docker runner + orchestrator
  keep their own runbook track; not part of plugin install.

### New `/setup` onboarding skill
- First-run skill: checks prereqs (git, `uv`, `gh`, `LINEAR_API_KEY`), interviews for
  the required config, writes a validated `dev-workflow.yml` from the bundled example,
  then points at the daily worktree workflow. Writes only that one local file — never
  commits, pushes, or moves a ticket. Mentions v2 but enables it only on explicit ask.

### New `/worktree` skill + parameterized worktree-reset.sh
- **`worktree-reset.sh` is now branch-model-agnostic.** It hardcoded `dev`/`main`
  throughout; it now reads `WORKTREE_TRUNK`/`WORKTREE_PROD` (defaulting to
  `dev`/`main`, so existing callers are unchanged) and drives every case guard,
  `origin/<trunk>` base, `origin/<prod>` hotfix base, sweep, and error line off
  them. `master` stays a guarded long-lived name; TRUNK==PROD is refused.
- **New `/worktree` skill** — two modes over that script: BOOTSTRAP offers the
  canonical-checkout + 2-4 `feature-[a-z]` slot layout and creates them; RESET
  (the default, from inside a slot) mints a fresh `<slot>-N` off the latest trunk,
  relinks shared state, sweeps merged branches, installs deps. It reads
  `repo.base_branch`/`repo.prod_branch`/`quality.bootstrap` and exports them as
  the script's env vars. The branch opinions are taught in-skill (never work on
  trunk/prod even with one worktree; feature → PR into base via `/cleanup` (no
  deploy); `/release` promotes base→prod and the human's merge deploys; hotfixes
  off prod). Its only outward action is the script's skippable merged-remote sweep;
  it never pushes, opens PRs, or touches the tracker. Wired into `/setup`'s
  handoff, the SessionStart brief, and both READMEs.
- **Root README now states the opinions inline** — a new *The opinionated
  workflow* section spells out the two-branch rules and the ideal
  `/worktree`→`/standup`→work→`/cleanup`→`/release` daily loop, instead of only
  linking the playbook.

### SessionStart auto-orientation hook
- A Claude Code SessionStart hook injects a short brief when a session opens in a repo
  that has a `dev-workflow.yml` (skills available + whether the v2 agent is on), and
  stays **silent** in every repo without one. Never blocks session start.

### Plugin-install config resolution
- Every skill's `dw-config` note now includes the plugin-install path
  (`uv run "${CLAUDE_PLUGIN_ROOT}/dev-workflow/dw-config.py" …`) alongside the hardened
  PATH shim and framework-checkout forms — a plugin-install user has neither of the
  latter two. Same treatment for release's `dw-telegram` fallback.

### Deterministic skill preambles + `dw-config --batch`
- New **batch mode**: `dw-config <yml> --batch key[=default] …` prints one
  shell-escaped `key=value` line per key in a single call (single-key mode unchanged;
  covered by `dev-workflow/test_dw_config.py`).
- Each interactive skill (standup, cleanup, release, blog-from-session, ticket-loop,
  setup) now opens its config section with ONE fenced preamble the model runs first —
  resolve the reader (PATH → `${CLAUDE_PLUGIN_ROOT}` → framework checkout), then a
  single `--batch` call loading every key that skill uses. No more per-key shell-outs
  mid-procedure; the preamble degrades to a clear "no config" line when
  `dev-workflow.yml` is absent, so the existing missing-config fallbacks still fire.

### Version-drift tooling
- `.version-bump.json` declares every file+field carrying the plugin version (today:
  `.claude-plugin/plugin.json` `.version`). `scripts/bump-version.sh` bumps them all
  (`<new-version>`), `--check`s for drift, or `--audit`s the repo for stray version
  strings that should be declared. Contributor docs point releases at it.

### Multi-project orchestrator (loop)
- **Round-robin scheduler** (`orchestrator/`) over the same runner image: roster load,
  marker-file work-tree guard, atomic orch-state, memory gate, window intersection,
  run-now, forced safety pass.
- **Four-class outcome classification** + backoff transitions with error/crash
  escalation; classification reads only the current pass's log segment.
- **PID-1 driver** — timeout process-group kill, secret-scoped passes, pre-check,
  drain, run-now; startup crash-recovery + boot lock-clear, pass-start write-ahead,
  status table. Offline smoke test.
- **Zero-cost waiting** via a peek-only pre-check + `orch.env` with a shared default
  bot; baked into the agent image with seed marker, deployment/rollout/onboarding docs
  (field-tested in the first `nt` rollout).

### Pass-outcome contract
- The skill writes `<state>/outcome.json` as its last act; `cron-run.sh` deletes any
  stale one at pass start so a crashed/killed pass is never classified from the
  previous pass's line. Annotated roster example.

### Queue-depth pre-check — `queue_count`
- New `queue_count` verb (`dev-workflow/queue-count.py`, GraphQL over `urllib`, keyed
  by `LINEAR_API_KEY`) — a Linear queue-depth pre-check sharing one filter definition
  with `list_actionable`, so the orchestrator can decide whether a pass is worth
  spending a session on without starting Claude.

### Telegram read-only peek
- New `telegram.py peek` subcommand — detects a pre-check poke without consuming the
  update offset (the interactive/loop drain still owns the offset).

### Docker fixes
- Default `LANG`/`LC_ALL` to `C.UTF-8` (the slim image ships no `en_US` locale,
  silencing per-pass `setlocale` warnings).
- `useradd` by absolute path (`/usr/sbin/useradd`) — the image `ENV PATH` omits
  `/usr/sbin`, which broke the build.

### Manifest metadata
- `plugin.json` → `0.5.0`; description covers all shipped skills + the tier model;
  added `repository`, `homepage`, and `keywords`. `marketplace.json` description synced.

## v0.4.0

### Telegram verbs — flag, list & prune questions (loop)
- **`flag: <what needs clearing>`** / **`flag NIP-123`** — file + flag, or flag an
  existing ticket, onto the weekly cleanup checklist (never queued for a build).
- **`questions`** / **`open questions`** — the loop replies with the open-question list.
- **`prune questions`** — the loop clears every question whose ticket is already
  Done/Canceled and releases the block.

### Manage open clarifying questions (CLI)
- **`dw-loop questions`** — list the loop's open clarifying questions (ticket, age, text).
- **`dw-loop questions --clear <id|TICKET>`** — drop a stale entry. Pure state edit:
  never sends to Telegram, never advances the Telegram offset.
- Questions now capture their **text + timestamp at ask time**; legacy bare entries
  (asked before this change) still load and render with `—` for text/age and sort
  first. Telegram can't cheaply re-fetch an old message, which is why capture happens
  at ask time going forward.
- Agent-side **prune**: clear every entry whose ticket is already Done/Canceled and
  release the ticket's block (documented in the ticket-loop skill).

### `dw-loop` is a real command
- The `--opt` install now writes `/usr/local/bin/dw-loop` — a wrapper pinned to the
  install's `TICKET_LOOP_LABEL` that execs the checkout's installer. Works in any
  shell; retires the hand-written `~/.zshrc` alias (now documented as clone-mode only).

### Fixes
- `dw-board` PATH shim used `os.path.abspath(__file__)`, which does not resolve
  symlinks, so invoked through `/usr/local/bin/dw-board` it looked for `dw-config.py`
  in `/usr/local/bin` and died with `FileNotFoundError`. Now uses `realpath` so the
  sibling resolves next to the real file; clear error if it's genuinely missing.

---

## v0.3.0

### Framework board tooling — `dw-board`
Config-driven Linear board tool (stdlib GraphQL over `urllib`). Credentials come from
the environment (`LINEAR_API_KEY`), never config. Replaces per-repo `linear-*.sh`.
- **`dw-board snapshot`** — regenerate board views, bucketed by configured `board.gates`.
- **`dw-board prune`** — report finished (Done/Canceled) tickets past
  `board.prune.threshold_days`. **Delete is off by default** (`allow_delete: false` →
  report only); set `true` (+ `--yes`) to trash.
- **`dw-board import [file]`** — bulk-create issues from a JSON holding file (default
  `<board.views>/import.json`); dry-run by default, `--yes` to create.

### Weekly board-hygiene digest (Mondays)
- 🧹 **Board hygiene** — flags shipped/deprecated tickets (from the prune report) and
  descriptions whose premise drifted. Flag + suggest only, never auto-closes.
- ☑️ **Flagged checklist** — weekly "clear these" list from `flagged`-labelled tickets;
  self-clearing as they resolve. Gated by a new `last_hygiene` weekly stamp.

### Dependency sequencing (loop)
- Mark a ticket blocked-by another; the loop labels it `dep_blocked` (inert-but-ready)
  and skips it until every blocker is Done, then auto-requeues on the next pass.
- New `get_blockers` tracker verb (Linear relations, or a `Blocked by: NIP-###`
  description convention).
- 🔗 **Blocked on dependencies** digest section — kept strictly distinct from the
  human-answer `blocked` label.

### Digest section contract
- Shared "board-derived digest section" contract (shared rendering, not shared logic);
  the existing `⏳ Blocked on answers` section references it, behaviour unchanged.

### CLI plumbing — `dw-config`
- PATH shim `dw-config` + a stdlib-only YAML fallback, so skills resolve
  `dev-workflow.yml` under a bare system `python3` (no PyYAML required).

### Config schema (all optional, type-checked in `validate.py`)
```yaml
board:
  gates: [publifai, launch, migrate]        # ordered gate-label precedence
  prune: { allow_delete: false, threshold_days: 7 }
tracker:
  roles:
    flagged:     { label: flagged }         # weekly checklist marker
    dep_blocked: { label: dep-blocked }     # dependency marker (distinct from blocked)
```

---

## Applying an update

A hardened (`--opt`) install copies the framework into `/opt`, so re-run the installer
to pick up new tools/skills and (re)create the PATH shims:

```bash
TICKET_LOOP_LABEL=<your-label> \
  <checkout>/skills/ticket-loop/install-cron.sh \
  --opt [--mcp-keyed] \
  --work-tree <target-repo> \
  --env-file <agent.env>
```

Then, per consuming repo, declare the config keys above in `dev-workflow.yml` and put
`LINEAR_API_KEY` in the loop's `agent.env` — features stay dormant until their keys
are present.
