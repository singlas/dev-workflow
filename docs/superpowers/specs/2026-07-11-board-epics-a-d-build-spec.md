# Build spec — Board tooling + hygiene + checklist + sequencing (Epics A–D)

**Date:** 2026-07-11
**Mode:** build all four, one batch, in two dependency-gated waves.
**Reviewed by:** Fable-model architect + Codex 0.144.1 — corrections baked in below.

## Locked decisions (from the two reviews + owner calls)

1. **Creds from env, never config.** The board tool loads `LINEAR_API_KEY` from the
   environment (same `.env` worktree-fallback niptao's scripts use). `dev-workflow.yml`
   declares only **team + buckets + policy knobs**. (`dev-workflow.example.yml:28-29`
   makes creds-in-config a rule violation.)
2. **B/C/D read the tracker via canonical verbs, not `board.views`.** The board views
   are throwaway snapshots only `standup` consumes. A is sequenced first for **cutover
   payoff**, not as a technical dependency.
3. **The "club" is a shared *rendering* contract, not a config DSL and not shared
   business logic.** A documented "digest section contract" in `ticket-loop/SKILL.md`;
   each feature keeps its own logic (B: detection, D: gating, C: pure label read).
4. **Import is ported** (was deferred; owner reversed the call). `dw-board import`
   ports `linear-import.sh` — bulk-create from a JSON holding file (default
   `<board.views>/import.json`), dry-run by default, `--yes` to create, team from
   config, key from env. niptao deletes its `linear-import.sh` after cutover.
5. **Prune stays, config-gated, delete OFF by default** (see schema). Default =
   report-only (which doubles as Epic B's hygiene input); opt-in to actually trash.
6. **D uses a DISTINCT marker, not `blocked`.** `roles.blocked.label` already means
   "waiting on a human answer" (`ticket-loop/SKILL.md:38,204`); overloading it corrupts
   digest + Telegram-unblock semantics. D gets its own `roles.dep_blocked` role + a new
   relations read. If Linear MCP `get_issue` doesn't return relations, fall back to a
   `Blocked by: NIP-###` **description convention parsed at triage** (zero adapter work).
   Auto-requeue is free: the 30-min poll re-runs `list_actionable` every pass.
7. **Schema + validator work is part of the foundation**, done once for all four epics.
8. **No prose policy in config.** Repo-specific policy (niptao's "audit-page = scrub")
   lives in repo docs / ticket bodies, not the yml.

## Config schema additions (all landed in wave 1)

```yaml
# Epic A — board tooling
board:
  snapshot: "..."               # existing (a command); framework tool becomes the value repos point to
  views: ".local/board"         # existing
  gates: [publifai, launch, migrate]   # NEW: ordered gate-label precedence (a flat label list; NO filter DSL)
  prune:                        # NEW
    allow_delete: false         # default: REPORT ONLY, never mutates. true => may trash (still needs --yes at run)
    threshold_days: 7           # Done/Canceled older than this are prune candidates

# Epic C — flagged checklist  (a new role under tracker.roles)
tracker:
  roles:
    flagged: { label: flagged }       # NEW role: the weekly "clear these" checklist marker

# Epic D — dependency sequencing  (a new role, distinct from blocked)
    dep_blocked: { label: dep-blocked }   # NEW role: inert-but-ready, waiting on a blocker ticket
```

`validate.py` must: accept these keys, keep them **optional** (a repo without them still
validates), enforce types (gates = list of strings; allow_delete = bool; threshold_days =
int > 0), and keep the tighten-only rule intact. Add `test_validate.py` cases for each.

## Wave 1 — foundation (build first)

**Deliverable 1: the framework board tool** (`dev-workflow/dw-board.py`, stdlib-only,
PEP-723 header like `dw-config.py`; GraphQL over `urllib`; reads `LINEAR_API_KEY` from env,
`tracker.team` + `board.*` from `dev-workflow.yml` via `dw-config.py`). Subcommands:
- `snapshot` — faithful port of niptao `scripts/linear-snapshot.sh`: query the team's
  issues, bucket by the config `board.gates` precedence, render markdown views into
  `board.views`. Preserve the proven query + bucketing; parameterize team/gates/creds.
- `prune [--yes]` — port of niptao `scripts/linear-prune.sh`: find Done/Canceled issues
  older than `board.prune.threshold_days`. **If `board.prune.allow_delete` is false: print
  the report and exit, never mutate** (dry-run is irrelevant — it cannot delete). If true:
  dry-run by default; `--yes` trashes via `issueDelete`. Only ever touches
  completed/canceled state types.
- PATH shim: install-cron.sh symlinks `/usr/local/bin/dw-board` like `dw-telegram`/`dw-config`.

**Deliverable 2: config schema** — the keys above in `validate.py` + `test_validate.py` +
annotated `dev-workflow.example.yml`, and README table rows.

Wave-1 verification: `python3 -m py_compile dev-workflow/dw-board.py dev-workflow/validate.py`;
`python3 dev-workflow/test_validate.py`; `dw-board snapshot`/`prune` run offline without a
key must fail with a clear "LINEAR_API_KEY not set" message, not a traceback. **Live
"proven against niptao" is a manual owner step, deferred — do not attempt live Linear calls.**

## Wave 2 — skill-prose layer (build after wave 1 lands; these all edit `ticket-loop/SKILL.md`)

**Deliverable 3: the digest section contract** — a short subsection in `ticket-loop/SKILL.md`
defining a reusable "board-derived digest section": emoji title, item-line shape, source =
role-resolved tracker query via canonical verbs, empty ⇒ omit. Existing `⏳ Blocked on
answers` is refactored to reference it (behavior unchanged — it still keys on the `blocked`
label + outstanding ❓ comment).

**Deliverable 4 (Epic C):** flagged-items checklist — a weekly digest section sourced from
`roles.flagged` tickets, self-clearing (re-queried each run; a closed/shipped ticket drops
off). Weekly cadence: append to a designated daily digest (Monday) gated by a new week-stamp
in `state.json` (`last_hygiene`, modeled on `last_scout`). Drop off = it's just a re-query,
no state to clear.

**Deliverable 5 (Epic D):** dependency sequencing —
- `tracker-adapters.md`: add a `list_relations`/`get_blockers` canonical verb (Linear
  mapping: `get_issue` relations if available, else the `Blocked by: NIP-###` description
  convention). Document the fallback.
- `ticket-loop/SKILL.md`: at triage (after the actionable list is built), for each candidate
  read its blockers; if any blocker is not in `roles.done.state`, skip it and ensure it
  carries `roles.dep_blocked.label` (inert-but-ready, not grabbed). A blocked ticket whose
  blockers are all Done is picked up normally on the next pass (auto-requeue is free).
- A `🔗 Blocked on dependencies` digest section (instance of the contract) listing each
  dep-blocked ticket and what it waits on.

**Deliverable 6 (Epic B):** weekly board-hygiene sweep — a weekly routine (same
`last_hygiene` cadence) that regenerates the board and flags shipped/deprecated tickets +
descriptions whose premises drifted. Consumes **prune's report-mode output** for the
shipped/deprecated half; the drift half is an agent judgement over ticket bodies.
Proportionate: **flag + suggest in the digest, never auto-close.**

## Non-goals / guardrails

- No filter-expression DSL in `board.gates` (narrow, n=1 — revisit only when repo #2 forces it).
- No answering/mutating from board CLIs beyond the gated prune.
- All B/C/D *mutations* (labeling, commenting) go through the canonical verbs, not the board CLI.
- Board CLI is a **read-only second seam** (except gated prune); note this in `tracker-adapters.md`.
