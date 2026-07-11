# Release notes

## Unreleased — targets v0.4.0

Not tagged yet. On `main` after `v0.3.0`.

### Manage open clarifying questions
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
