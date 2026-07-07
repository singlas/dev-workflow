# ticket-loop — a coding agent you manage from a group chat

An autonomous ticket loop built from plain Claude Code primitives — **no agent
framework, no orchestrator service, nothing to host.** A Claude Code session
works your Linear board: it takes approved tickets, asks clarifying questions in
a Telegram group, implements each ticket in an isolated git worktree, and opens
one reviewable PR per ticket — then **babysits that PR like an employee would**:
addresses your review comments and failing CI, heals merge conflicts, closes the
ticket when the PR merges, and reports in with a once-a-day digest. Anyone on
the team — including non-engineers — reports bugs and features by typing (or
dropping a screenshot) in the group.

The entire system is this folder:

| File | What it is |
|---|---|
| `SKILL.md` | The orchestrator — a Claude Code skill. The whole agent's behavior, including its security guardrails, lives here in plain English. |
| `telegram.py` | The Telegram bridge — ~280 lines, Python stdlib only. `send` / `send-photo` / `poll` / `discover` subcommands wrapping `sendMessage`, `sendPhoto`, and long-polled `getUpdates`. Inbound photos are downloaded locally so the agent can look at bug screenshots. |
| `env.example` | The two env vars the bridge needs. |

## What you need (dependencies)

- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — the skill
  runs inside a Claude Code session. Continuous mode uses `/loop`; a single
  pass works in any session.
- **A [Linear](https://linear.app) workspace + the Linear MCP** wired into
  Claude Code (`claude mcp add`). Linear is the state store — swap-able for
  another tracker by editing SKILL.md, the loop only needs labels + comments.
- **[`gh` CLI](https://cli.github.com/), authenticated** — the agent opens PRs
  with it.
- **`python3`** — any version; the bridge is stdlib-only, nothing to pip-install.
- **A Telegram bot + a dedicated group** (free, ~5 minutes via @BotFather).
- **A git repo with an integration branch** (`dev` in the skill text; adjust if
  your trunk is `main`).

## Setup

1. **Copy this folder** into your repo at `.claude/skills/ticket-loop/`.
2. **Create the bot:** message [@BotFather](https://t.me/BotFather) → `/newbot`
   → copy the token.
3. **Disable the bot's privacy mode** (@BotFather → `/setprivacy` → Disable,
   then remove + re-add the bot to the group). Without this the bot cannot see
   plain group messages — they vanish silently.
4. **Create a dedicated group**, add the bot, send one message, then:
   `python3 .claude/skills/ticket-loop/telegram.py discover` → grab the chat id.
5. **Set the env vars** — copy `env.example` values into your repo-root `.env`
   (or export them). Add `.agent-loop/` to `.gitignore` (poll offset + downloaded
   media live there).
6. **Create the Linear labels:** `agent` (approved to build), `agent-blocked`
   (waiting on an answer), `manual` (humans only — the agent refuses these).
7. **Skim SKILL.md's "Conventions" block** and adjust the integration branch /
   test commands to your repo. Issue keys need no config — any `TEAM-123` key
   matches.
8. **First run supervised:** `/ticket-loop --dry-run`, then go live with
   `/loop /ticket-loop` in a dedicated worktree session.

## The group-chat grammar

| You type in Telegram | What happens |
|---|---|
| `bug: <what's broken>` | Linear issue created (labeled Bug, reporter credited) + a `take it? (go/skip)` proposal |
| `feature: …` / `ticket: …` | Same, labeled Feature / unlabeled |
| `go` (reply to a proposal) | The `agent` label is applied — approved to build |
| `take ABC-123` | Green-light an existing ticket directly |
| Reply to a ❓ question, or `ABC-123 <answer>` | Answer recorded on the ticket; it unblocks |
| A screenshot (with optional caption) | Downloaded locally; the agent reads it as evidence and attaches the context to the ticket |
| `stop` / `hold` (during a build) | The build aborts — branch kept, ticket skip-listed, reason commented |

The agent posts back: ❓ clarifying questions, 🔨 when it starts a build,
✅ with the PR link (and ✅ again when the PR merges and the ticket closes),
🔁 when it has addressed review feedback and updated a PR, ⚠️ on failures,
🔀 when it heals a conflicted PR, 🙋 proposals when the queue runs empty (it
scouts your backlog for agent-suitable tickets rather than going idle — still
approval-gated), and one morning digest: merged / awaiting review / blocked on
answers / queued (`--report` triggers it on demand, e.g. from cron).

## Safety model (the part that matters)

- **Nothing is built without an explicit human `go`.** The `agent` label means
  *approved*, and it is only ever applied through the group. A `manual` label
  fences a ticket off entirely.
- **Ticket text is data, not instructions.** SKILL.md carries explicit
  prompt-injection guardrails: operational instructions inside tickets or
  messages ("push to main", "skip the tests", "read the .env") are refused and
  surfaced to the group instead. Screenshots get the same treatment.
- **Every change is a PR** into your integration branch — the agent merges
  nothing, force-pushes nothing, and never touches `main`. Agent PRs are
  marked `[agent]` in the title.
- **One ticket at a time**, in a fresh isolated worktree per ticket, with a
  diff-size sanity check before anything is pushed.
- **State lives on the tickets** (labels + comments), not in the session — kill
  the loop and restart cold, nothing is lost. The only local state is
  `.agent-loop/state.json` — the Telegram poll offset and the last-digest date
  (plus a `last-batch.json` crash-recovery copy of the most recent poll).

## Things that will bite you

- **Telegram bot privacy mode** (setup step 3) — the silent killer.
- **`getUpdates` retains messages ~24h.** A loop that's off overnight is fine;
  off for a weekend loses messages sent in the gap.
- **Emoji reactions never reach the bot.** A 👍 reaction on a proposal is
  invisible — approvals must be typed (`go`).
- **People reply to the bot's *latest* message, not the question.** The
  `ABC-123 <answer>` prefix convention is the workhorse; reply-matching is the
  bonus.

From the team at [Niptao](https://niptao.com) — the write-up with the full story
is on [our blog](https://niptao.com/blog/an-engineer-you-manage-from-a-group-chat/).
