# Release notes

## v0.5.0

**Tiered install + the multi-project orchestrator.** The plugin now presents three
tiers in one install, and the autonomous loop grew a round-robin orchestrator for
running many repos on one box.

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
