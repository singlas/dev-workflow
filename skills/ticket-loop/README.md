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
| `telegram.py` | The Telegram bridge — Python stdlib only. `send` / `send-photo` / `send-document` / `poll` / `discover` subcommands wrapping `sendMessage`, `sendPhoto`, `sendDocument`, and long-polled `getUpdates`. Inbound photos are downloaded locally so the agent can look at bug screenshots. |
| `loop-lock.sh` | A shared singleton lock so a scheduled pass and an interactive `/loop` session never run at once (no double-drained Telegram offset, no double-builds). |
| `cron-run.sh` / `run-pass.sh` / `install-cron.sh` | Optional always-on: one headless pass under the lock. `cron-run.sh` is the config-driven runner (laptop launchd or container); `run-pass.sh` is the in-container entrypoint; `install-cron.sh` is the macOS launchd installer (adapt for Linux cron/systemd). |
| `docker/` | The containerized deployment — `Dockerfile`, `loop-mcp.json`, systemd unit templates, and a runbook (`docker/README.md`). |
| `env.example` | The two env vars the bridge needs, plus the optional runner env. |

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

## Run it always-on (optional)

Beyond `/loop` in a live session, this folder ships a macOS **launchd** variant so
the loop runs headless on a schedule even when no session is open:

- `loop-lock.sh` — the singleton lock both the scheduled pass and any interactive
  `/loop` honour, so they never overlap.
- `cron-run.sh` — runs one headless pass under the lock. It uses
  `--dangerously-skip-permissions` (there's no human to approve tool calls when
  unattended); it's bounded by the SKILL's own guardrails and worktree-isolated
  build subagents. Understand that trade-off before enabling it.
- `install-cron.sh` — `TICKET_LOOP_WORKTREE=/path/to/worktree install-cron.sh`
  loads a LaunchAgent that runs a pass every 30 min, 09:00–20:00 local; the daily
  digest rides the first pass of each day. `--refresh` pulls the worktree up to
  `origin/dev`; `--uninstall` removes it. On Linux, point cron or a systemd timer
  at `cron-run.sh` instead.

### Config-driven runner + optional `dev-workflow.yml`

`cron-run.sh` reads the target repo's `dev-workflow.yml` (via
`dev-workflow/dw-config.py`) when present, so the same runner drives any repo:
`repo.base_branch` (the branch it resets to and PRs target), `build.model` (pins
`--model`), `schedule.tz` (the digest's "new day"), `runtime.state_dir`, and a
`hooks.pre_pass` command run before each pass. With no config file it degrades to
sane defaults (base `dev`, no `--model`, system timezone, `.agent-loop`). Env vars
override the config — see `env.example` for `DW_WORK_TREE`, `DW_PLUGIN_DIR`,
`DW_SKILL_INVOCATION`, `DW_ENV_FILE`, `TICKET_LOOP_STATE_DIR`, and the
`TICKET_LOOP_*` knobs.

### Run it in a container (systemd timer)

For a headless host, `docker/` packages the loop as a pinned image that bakes the
runner + plugin root-owned at `/opt/dev-workflow` and runs one pass per tick against
a mounted work-tree volume. Full runbook: [`docker/README.md`](docker/README.md) —
build (with a required `CLAUDE_CODE_VERSION` pin), seed the volume, write
`agent.env`, and render the `agent.service`/`agent.timer` templates. Secrets stay on
the volume (never baked, never in `docker inspect`).

### Run natively (macOS launchd) — laptop or a dedicated Mac mini

Same runner and skills as the container, minus the container. `install-cron.sh` grows
an **external-runner** mode: instead of a checkout driving its own `cron-run.sh`, the
LaunchAgent runs the *framework's* `run-pass.sh` against a **separate** target repo —
the runner lives outside the work tree it drives (the read-only-runner property the
container gets from boundary rule 2, on bare macOS).

- **Native** when you don't want container tooling on the machine — a laptop trialling
  the loop, or a dedicated Mac mini. Add `--opt` to copy the runner + plugin root-owned
  to `/opt/dev-workflow` so the agent's own account can't edit its leash (this keeps the
  read-only-runner property; without it the plist points at your clone, which the agent
  user could modify).
- **Docker** when you want hard isolation — a non-root user, dropped capabilities, and a
  read-only rootfs with the work tree as the only writable mount. Reach for it on a
  shared or exposed host.

Worked example (framework clone drives a separate target repo, hardened):

```
git clone https://github.com/singlas/dev-workflow ~/dev-workflow
mkdir -p ~/dev-workflow/.local        # gitignored — secrets live with the clone, never in git
$EDITOR ~/dev-workflow/.local/agent.env && chmod 600 ~/dev-workflow/.local/agent.env
~/dev-workflow/skills/ticket-loop/install-cron.sh \
  --work-tree ~/repos/your-repo --opt --mcp-keyed
```

`--work-tree` is the repo the loop builds against (must be a git checkout with a
`dev-workflow.yml` at its root). `--env-file` is the `agent.env` secrets file
`run-pass.sh` sources (mode `600`; it's warned about, never printed) — when omitted,
the installer defaults to the clone's gitignored `.local/agent.env` if it exists,
as above. `--mcp-keyed`
wires the keyed tracker MCP so Linear needs a static `LINEAR_API_KEY` instead of a
browser OAuth — required on any headless box. `--refresh`/`--uninstall` work as in the
legacy mode; with no new flags the script is byte-for-byte its old in-tree self.

**Dedicated Mac mini.** For an always-on agent host:

- Run it under a **separate macOS user** created just for the agent — its home holds the
  clone, the `agent.env`, and `~/.claude` auth, nothing of yours.
- Authenticate headlessly: `claude setup-token` once, then put the resulting
  `CLAUDE_CODE_OAUTH_TOKEN` in the env file. With `--mcp-keyed` there's **no browser
  step** anywhere in the loop.
- Keep it awake: System Settings → Energy Saver → *Prevent automatic sleeping*, or wrap
  the schedule with `caffeinate -s`. A sleeping Mac fires no LaunchAgent.
- **One loop at a time, anywhere.** The pid lock (`loop-lock.sh`) is local — it can't
  arbitrate across machines. Install **exactly one** schedule per repo across every host
  (laptop + mini included); two schedules on the same board double-drain Telegram and
  double-build.

### Install as a Claude Code plugin

`ticket-loop` ships inside the **`dev-workflow`** plugin (manifest at
`.claude-plugin/plugin.json`). Install it with `claude plugin install` (plugin name
`dev-workflow`), or point Claude Code at a checkout with `--plugin-dir <path>` and
invoke `/dev-workflow:ticket-loop`. The container runner does exactly this — it
passes `--plugin-dir /opt/dev-workflow/plugin` when the pinned `claude` supports the
flag, and falls back to a repo-local `/ticket-loop` (with a logged warning) when it
doesn't.

## The group-chat grammar

| You type in Telegram | What happens |
|---|---|
| `bug: <what's broken>` | Linear issue created (labeled Bug, reporter credited), labeled `agent`, and the loop **investigates it** — no go/skip gate |
| `feature: …` / `ticket: …` | Same — created, labeled `agent`, then scoped/planned before any build |
| `take ABC-123` | Green-light an *existing* backlog ticket into the queue |
| `go` (reply to a 🙋 scout proposal) | Approves a ticket the loop proposed when the queue ran empty |
| Reply to a ❓ question, or `ABC-123 <answer>` | Answer recorded on the ticket; it unblocks |
| A screenshot (with optional caption) | Downloaded locally; the agent reads it as evidence and attaches the context to the ticket |
| `stop` / `hold` (during a build) | The build aborts — branch kept, ticket skip-listed, reason commented |

The agent posts back: ❓ clarifying questions, 🔨 when it starts a build,
✅ with the PR link (and ✅ again when the PR merges and the ticket closes),
🔁 when it has addressed review feedback and updated a PR, ⚠️ on failures,
🔀 when it heals a conflicted PR, 🙋 proposals when the queue runs empty (it
scouts your backlog for agent-suitable tickets at most once a day rather than
pinging every pass — still approval-gated), and one morning digest: merged /
awaiting review / blocked on answers / queued (`--report` triggers it on demand,
e.g. from cron).

## Safety model (the part that matters)

- **The loop looks before it builds; the human gates the outcome, not the
  glance.** A reported bug or feature is investigated first (read-only); the loop
  builds only when the fix/approach is clear, otherwise it comes back with a
  scoped question or a short plan. The real gates are that clarifying question and
  the **PR review** — every change is a reviewable PR the agent never merges. A
  `manual` label fences a ticket off entirely; an *older backlog* ticket the loop
  wants to pick up is still `take`-approval-gated.
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
