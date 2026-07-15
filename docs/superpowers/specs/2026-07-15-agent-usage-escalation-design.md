# Agent usage tracking + token-exhaust escalation

**Status:** approved (Codex-reviewed 2026-07-15) · **Scope:** `skills/ticket-loop/`

## Problem

Headless ticket-loop passes run in Docker on the nt box: niptao + rasa via the
orchestrator (round-robin), paytunes as a standalone systemd timer (single-mode).
Auth is a shared Claude **subscription** OAuth token (session limits, not metered).

On 2026-07-14→15 the shared token hit its session limit. Single-mode paytunes
logged `You've hit your session limit · resets Npm`, exited 1 every 30-min tick
for ~15h, and **nobody was paged** — single-mode has no orchestrator escalation
path. There is also no per-agent usage visibility.

## Goals

1. **Escalate immediately** when a pass hits the session limit (or hard-fails),
   to the **ops channel** — covering single-mode, which has no orchestrator.
2. **Track per-agent usage** — tokens/turns/duration/rc/limit-events per pass —
   surfaced as a **daily ops rollup**. No dollar cost (it's $0 on a subscription).
3. Add **zero** daily Claude/subscription token cost (all code, no model calls).
4. Do not disturb the currently-healthy niptao/rasa passes.

## Non-goals

- Real per-token dollar accounting (would require moving the box to a metered
  `sk-ant-api` key — separate project, different billing model).
- Per-tenant digest usage lines (ops rollup only).

## Design (Codex-revised)

### 1. Per-pass usage capture — `cron-run.sh` + `usage-parse.py`

Switch the pass to `claude -p --output-format json` (single-result object on
2.1.210, confirmed). Capture **stdout and stderr to separate temp files**, not
straight to the log. A new baked helper `usage-parse.py` reads them and:

- extracts `.result` → written to the cron log (**human summary preserved, log
  looks as today**);
- appends one record to `<state>/usage.jsonl`:
  `{ts, tenant, input_tokens, output_tokens, cache_read, cache_creation,
    num_turns, duration_ms, total_cost_usd, rc, limit, reset}`.
  `total_cost_usd` is nullable/diagnostic; **a missing field never fails the
  pass** (the CLI documents `json` mode but not its schema).

**Sentinel + limit detection run against the RAW captured stdout+stderr**, never
the parsed `.result` — because the guillotine line and the limit notice are
harness-level and may be non-JSON / on stderr (Codex [P1]). Detection is
**broadened**: match `session limit` / `limit reset(s)` / `hit your … limit`
case-insensitively (the exact phrase `hit your session limit` is **not** in the
2.1.210 binary; `session limit` and `limit resets` are). The existing
`Background tasks still running` guillotine check moves from `tail $LOG` to the
raw capture.

### 2. Escalation → ops channel, immediate, deduped — `cron-run.sh`

After the pass exits, `cron-run.sh`:

- **session-limit** detected → dedup + send ops alert `⚠️ <tenant>: Claude
  session limit — resets <time>`.
- **hard failure** (rc≠0 AND no `outcome.json` AND not a limit) → ops alert with
  the last log lines.
- **Secret scoping (Codex [P1]):** ops creds are **never injected into the pass
  env** and never persisted to a project env file. `notify_ops()` sources
  `ORCH_TELEGRAM_BOT_TOKEN`/`ORCH_TELEGRAM_CHAT_ID` from `DW_OPS_ENV_FILE`
  (default `/home/agent/orch.env`) **in a one-shot subshell, after the claude
  child has exited**, and passes them to `telegram.py send` as
  `TELEGRAM_BOT_TOKEN`/`AGENT_TELEGRAM_CHAT_ID`. The `claude -p` process never
  sees them.
- **Only in single-mode.** The orchestrator sets `DW_ORCHESTRATED=1` in the pass
  env; when set, `cron-run.sh` does **not** send (the orchestrator owns
  escalation for niptao/rasa via its existing threshold path). Single-mode
  (flag unset) pages immediately — closing the outage gap.
- **Dedup** via `<state>/alert.json` = `{kind, fingerprint, reset_at}` (Codex
  [P2]): suppress re-alert while the same `(kind,fingerprint)` holds and, for a
  limit, until `reset_at` passes; cleared on the next successful pass. Handles
  reset-time-passing, limited→hard-fail transition, and stale-latch-after-recovery.

### 3. Daily ops rollup — `usage-rollup.py` + `orchestrator.sh`

`usage-rollup.py` scans **`<state-root>/*/usage.jsonl`** (all tenants, incl.
paused/single-mode paytunes — Codex [P2]: the rollup must not read only
roster-*enabled* projects) for the given day, aggregates per tenant
(`passes · in/out tokens · limit-hits`) + fleet totals, and prints a summary to
stdout. `orchestrator.sh` runs it **once per day** (timestamp-gated at the loop
top) and sends the output via the existing `ops_alert()` (no model call).

### 4. State-dir unification — deploy step

Point `paytunes.service` at `TICKET_LOOP_STATE_DIR=/home/agent/state/paytunes`
(was `/home/agent/paytunes/.agent-loop`) so the rollup's `<state-root>` scan
finds it. One-time migrate the existing `state.json`.

## Deployment

Baked framework files change → **rebuild `dw-agent:2.1.207`** (same Claude pin),
restart orchestrator + paytunes timer, re-render paytunes.service, migrate
paytunes `state.json`. The Dockerfile must bake `usage-parse.py` +
`usage-rollup.py`.

## Tests

- `usage-parse.py`: json parse, missing-field tolerance, non-JSON failure path,
  limit-detection regex (incl. the 2.1.210 wording), reset extraction.
- `usage-rollup.py` aggregation (pure function) — extend `test_orch.py` or a
  sibling.
- `bash -n` on `cron-run.sh` + `orchestrator.sh`; `py_compile` on new py.

## Open risk

The live limit-failure transport (JSON stdout vs stderr vs both) is undocumented;
the parser tolerates all three (reads raw stdout+stderr for detection).
