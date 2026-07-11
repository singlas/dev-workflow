# Design: surface & clear open clarifying questions (ticket-loop)

**Date:** 2026-07-11
**Status:** Approved (design), pending implementation plan
**Touches:** `skills/ticket-loop/telegram.py`, `skills/ticket-loop/install-cron.sh`,
`skills/ticket-loop/SKILL.md`, a new stdlib test, a one-line README/docstring note.
**Does not touch:** the tracker adapter contract, `dev-workflow.yml`.

## Problem

A repo owner running the ticket-loop cannot see the clarifying questions the loop
has asked. `state.json` records only `questions: {message_id: "ABC-123"}` — a
routing table so a Telegram reply matches a ticket. `dw-loop status` can therefore
only *count* them (`open Qs : N awaiting answers`); it cannot show the text, the
ticket, or the age, and there is no way to clear an entry that will never be
answered (e.g. the ticket was closed out-of-band). The counter drifts from reality
and tickets sit **blocked** on answers nobody will give.

## Goals (acceptance criteria)

1. **Capture text at ask time.** Persist `{message_id, ticket, question_text, asked_at}`
   when a question is posted, because Telegram cannot cheaply re-fetch an old
   message by ID. Legacy bare `{message_id: "ABC-123"}` entries still load.
2. **List them.** `dw-loop questions` shows each open question: ticket, age, and the
   first lines of text.
3. **Clear one.** `dw-loop questions --clear <id|TICKET>` drops a single entry (by
   message_id) or all entries for a ticket key.
4. **Prune the dead.** `--prune` drops every entry whose ticket is already
   Done/Canceled on the tracker, showing what goes and why *before* applying.
5. **Release the hold.** A cleared entry releases the ticket's "waiting on answer"
   hold so the next pass handles it normally.

### Safety rails

- Clearing **never** advances the Telegram offset and **never** sends a message.
- Clearing is idempotent and atomic (existing tmp-write + replace in `save_state`).
- List/clear need no secrets (no Telegram token, no tracker access).

### Non-goal

Answering from the CLI. Replies stay in Telegram so the question/answer audit trail
on the ticket is unchanged.

## Key constraint that shaped the architecture

Everything shell/stdlib in this repo — `dw-telegram`/`telegram.py`, `dw-loop`/
`install-cron.sh` — has **zero tracker access**. Only the agent reaches the tracker
(Linear via MCP, through the canonical verbs). Therefore:

- **List** and **`--clear <id|TICKET>`** are pure `state.json` edits → they live in
  the CLI and run standalone, no tracker, no secrets.
- **`--prune`** needs a tracker *read* ("is this ticket Done/Canceled?").
- **Releasing the blocked-label hold** needs a tracker *write*.

Both of the latter are **agent-side**, documented as a SKILL procedure. Decision
recorded: *agent-driven prune; CLI does list + clear.* (Rejected alternatives: a
`tracker.state` config command — expands the adapter contract, every repo must
supply it; pruning from the local board snapshot — depends on stale/incomplete
snapshots, risks pruning the wrong entries.)

## Design

### Component 1 — rich question entries (`telegram.py`)

`state.json.questions` changes shape:

```json
{
  "4567": {
    "ticket": "ABC-123",
    "text": "❓ ABC-123 — <title>\n1. <question>",
    "asked_at": "2026-07-11T14:03:00Z"
  }
}
```

- **Written by** the existing `--ticket` path in `cmd_send`, and for consistency
  `cmd_send_photo` / `cmd_send_document` (there `text` is the caption). `asked_at`
  is `datetime.datetime.now(datetime.timezone.utc)` serialized ISO-8601 with a `Z`.
- **Backward compatible read.** A tiny accessor resolves either shape:

  ```python
  def _q_ticket(v):
      return v if isinstance(v, str) else v.get("ticket")
  ```

  Legacy bare-string entries load unchanged; their `text`/`asked_at` are absent and
  render as `—` / unknown age.
- **Readers updated to use the accessor:** `match_ticket(msg, questions)` resolves
  the ticket via `_q_ticket`. `cmd_poll` still pops the entry by `message_id`
  (unchanged key), so reply-consumption and follow-up re-recording behave exactly
  as before.

### Component 2 — CLI surface

**`telegram.py questions` (new subcommand):**

- No flag → **list**. One block per entry, sorted oldest-first by `asked_at`
  (unknown/legacy age sorts first — most likely stale). Format:

  ```
  ABC-123  msg 4567  asked 3d ago
      ❓ ABC-123 — <title>
      1. <first question line>
  ```

  First 1–2 lines of text, each truncated to a sane width.
- `--json` → emit the raw entry list (message_id, ticket, text, asked_at) for the
  agent to consume during prune.
- `--clear <id|TICKET>` → if the argument is all digits, clear that one
  `message_id`; otherwise treat it as a ticket key (case-insensitive) and clear
  **every** entry for that ticket (a ticket may carry a follow-up question).
  Prints each cleared entry. **Never** calls the Telegram API; **never** reads or
  writes `offset`. If nothing matches, prints a clear message and exits non-zero.

**`dw-loop questions [--clear X] [--json]` (install-cron.sh forwarder):**

- Resolves the loop's state dir *exactly* as the `status` subcommand does today
  (plist env → `dev-workflow.yml` `runtime.state_dir` → `.agent-loop`). The
  resolver is factored out of `status` into one shared helper so both stay in sync.
- Runs `telegram.py questions …` with `TICKET_LOOP_STATE_DIR=$SD`, reusing the same
  baked-vs-framework path resolution already used for `dw-config`/`telegram.py`.
- The `status` `open Qs` line gains a hint: `open Qs : N awaiting answers (dw-loop
  questions to list)`.

### Component 3 — agent procedure (`SKILL.md`, new short subsection "Clearing stale questions")

- **Prune (agent-run, needs the tracker):** `dw-telegram questions --json` → for
  each entry call the canonical `get_ticket` verb → collect those whose state is
  **Done/Canceled** → print the go-list (ticket, age, first line, tracker state)
  **before applying** → on confirm, `dw-telegram questions --clear <message_id>`
  each and drop any stray **blocked** label. (A Done/Canceled ticket is not
  reworked, so the label drop there is tidiness.)
- **Hold-release as next-pass reconciliation:** during the normal pass, a
  **blocked**-labeled ticket with *no outstanding question entry* in `state.json`
  is treated as "answer no longer pending" — the agent removes the **blocked**
  label and re-evaluates the ticket as normal actionable work. This is the
  mechanism that makes a human's bare `dw-loop questions --clear ABC-1` (when nobody
  will answer) actually unblock the ticket, with no Telegram round-trip and no CLI
  tracker access.
- **Non-goal reinforced:** never answer from the CLI; replies stay in Telegram so
  the ticket's question/answer audit trail is unchanged.

### Component 4 — tests

Add a stdlib `unittest` (no network) for the new pure functions:

- `_q_ticket` accessor over both the rich shape and a legacy bare string.
- Age / first-line formatting (including a legacy entry with no `asked_at`).
- Clear-by-id (one entry) vs clear-by-ticket (all entries for a key), and the
  no-match → non-zero path.
- **Invariant:** a clear operation leaves `offset` untouched and sends no request.

Plus a manual pass exercising `questions` and `--clear` against a scratch
`state.json`.

## Data flow

```
ask question:   cmd_send --ticket ABC-123  ->  questions["4567"] = {ticket,text,asked_at}
                                            ->  agent sets blocked label on tracker
answer arrives: cmd_poll  ->  match_ticket (via _q_ticket)  ->  questions.pop("4567")
                                            ->  agent mirrors answer, removes blocked label
inspect:        dw-loop questions           ->  telegram.py questions (reads state.json)
clear (human):  dw-loop questions --clear ABC-1  ->  questions.pop(...)   [offset untouched]
                                            ->  next pass: blocked + no entry -> unblock
prune (agent):  dw-telegram questions --json -> get_ticket per entry -> --clear the Done/Canceled
```

## Error handling

- Corrupt `state.json` already exits with a descriptive error in `load_state`; the
  new subcommand inherits that.
- `--clear` with no match: descriptive message, non-zero exit, no write.
- Legacy entries: never crash a list; render `—` for missing text/age.
- Forwarder when the loop was never run from this work tree: `dw-loop questions`
  reports "no state.json at <dir>" the same way `status` does.

## Out of scope

- Answering/replying from the CLI.
- Any change to the tracker adapter contract or `dev-workflow.yml` schema.
- Reminders / escalation of aged questions (already handled by the digest's
  "Blocked on answers" section).
