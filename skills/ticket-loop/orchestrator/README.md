# ticket-loop orchestrator — one box, N projects

CI-for-ticket-work, multiplied: a single long-lived process round-robins N
ticket-loop projects **sequentially** (never two passes at once), each with its
own repo clone, Linear board, Telegram group + bot, and secrets file. It
replaces the *scheduler*, not the *runner* — every turn shells out to the same
`run-pass.sh → cron-run.sh → claude -p /ticket-loop` chain the single-project
shapes use.

Design: `docs/superpowers/specs/2026-07-11-ticket-loop-orchestrator-design.md`.

## The axes (composable, not bundled)

| Axis | This directory provides | The alternative stays first-class |
|---|---|---|
| Mode | **orchestrator** (roster of N) | single-project runner (`install-cron.sh`, `docker/` timer) |
| Cadence | **adaptive** (pre-check + `10m→20m→40m→60m` ladder) | `fixed` (constant interval — set `cadence: fixed`) |
| Packaging | containerized (the existing image + an explicit command) | bare (`orchestrator.sh` under systemd on any host) |
| Host | an always-on box | a laptop |

## How a turn works

```
orch.py next            → run <project>, or sleep to min(next_eligible)
  memory gate           → MemAvailable < 2.5 GiB? skip turn (short requeue)
  window                → roster window ∩ repo schedule.window (skip ≠ ladder)
pre-check (adaptive)    → queue-count.py (Linear depth) + open questions
                          + telegram.py peek (read-only) — all idle? back off
orch.py pass-start      → crash write-ahead
run-pass.sh (timeout,   → the unchanged per-pass runner, child env scoped to
  process-group kill)     ONLY this project's DW_ENV_FILE/WORK_TREE/STATE_DIR
orch.py classify        → productive | dry | waiting | error | skipped-lock
                          (from the skill's outcome.json — see SKILL.md)
orch.py record          → ladder / waiting interval / error streak / park;
                          escalate to the project group + the ops channel
```

Outcome → cadence: **productive** resets to the fast rung; **dry** advances the
ladder (quiet nights back off to the 60m cap on their own — no night mode);
**waiting-on-human** polls at a fixed 20m (polling faster doesn't make humans
answer faster); **error** counts a streak and escalates at 3; a crash-looping
project is parked for 12h after 3 consecutive crashes. A forced full pass runs
every 8h per project regardless of pre-check, so pre-check drift can never
silently starve a board.

## Deployment (docker, the nt shape)

Build the existing image (from the repo root — the Dockerfile already bakes
the orchestrator):

    docker build -f skills/ticket-loop/docker/Dockerfile \
      --build-arg CLAUDE_CODE_VERSION=<pin> -t dw-agent:<pin> .

Volume layout (one mounted volume holds everything writable):

    /home/agent/
      roster.yml            # the roster (start from `roster.example.yml`, next to this README)
      orch/                 # orchestrator state: orch-state.json, run-now
      <project>/            # dedicated base-branch clone + .dw-agent-clone marker
      <project>.env         # 600 — LINEAR_API_KEY, GH_TOKEN (fine-grained,
                            #   per-repo PAT), TELEGRAM_BOT_TOKEN, chat id
      state/<project>/      # state.json, loop.lock, logs, outcome.json

Seed each work tree as a **dedicated clone** and `touch <tree>/.dw-agent-clone`.
NEVER point a roster entry at a live/prod checkout: every pass runs
`git reset --hard origin/<base>` plus the repo's bootstrap/pre-pass hooks in
that tree. The marker + volume-root allowlist makes the orchestrator refuse
anything else at startup.

Run (all caps non-negotiable on a shared prod box — see the spec's Capacity
section):

    docker run -d --name dw-orchestrator \
      --restart unless-stopped --init \
      --network host \
      --memory=2g --memory-swap=2g --cpus=1 --pids-limit 512 \
      --stop-timeout 5460 \
      --log-opt max-size=10m --log-opt max-file=3 \
      -v dw-agent:/home/agent \
      -e ORCH_TELEGRAM_BOT_TOKEN=<ops bot> -e ORCH_TELEGRAM_CHAT_ID=<ops group> \
      dw-agent:<pin> /opt/dev-workflow/bin/orchestrator.sh

Notes:
- `--init` + the SIGTERM drain: `docker stop` lets the current pass finish or
  hit its timeout — hence the generous `--stop-timeout` (> pass_timeout).
- `--memory-swap` equal to `--memory`: no extra swap beyond RAM.
- The ops channel env vars are the ONLY secrets in the orchestrator's own env;
  per-project secrets live in the per-project env files, sourced by each pass.
- `docker logs -f dw-orchestrator` is the live dashboard (one line per turn).
- Status: `docker exec dw-orchestrator python3 /opt/dev-workflow/bin/orch.py \
    status --roster /home/agent/roster.yml --state /home/agent/orch/orch-state.json`
- Run one project now: `docker exec dw-orchestrator \
    bash -c 'echo <name> > /home/agent/orch/run-now'`

## Onboarding a project (the real critical path)

The loop is tracker-driven; a project can't be round-robined until it has:
1. `dev-workflow.yml` at its repo root (validate: `uv run dev-workflow/validate.py <file>`).
2. A Linear team with the queue/blocked/exclude/done roles mapped in
   `tracker.roles`, and at least one eligible ticket.
3. A Telegram group + a **dedicated** bot (own token + chat id — never share a
   bot across projects: getUpdates offsets contend).
4. A per-project env file (600, e.g. `<project>.env`) with `LINEAR_API_KEY`, a **fine-grained per-repo**
   `GH_TOKEN`, and the Telegram creds. One PAT across orgs is a prompt-injection
   blast-radius mistake — a malicious ticket on project A must not be able to
   push to project B's org. (Residual risk in the one-container shape: passes
   run as one uid, so B's env file is readable from A's build subagent —
   accepted for single-owner rosters; the isolated-per-container shape is the
   upgrade path.)
5. A dedicated clone on the volume + the `.dw-agent-clone` marker + a roster entry.

## Rollout sequence (nt)

1. Deploy with **niptao only** in the roster; watch several days of decision
   lines (four-class outcomes, ladder behavior, the memory gate under celery
   bursts, the docker-mem sampler).
2. **Decommission niptao's individual cron/launchd job** — two schedulers must
   never drive one project (they fight over the board and the Telegram offset;
   the singleton lock is a safety net, not a license).
3. Add whichever of rasa/paytunes has a board; then the last one. (rasa first
   needs its branch-model decision — single `main` = base = prod, or a `dev` trunk.)
4. Confirm during the watch period whether niptao's runtime `claude -p` shares
   a rate-limit pool with the loop's OAuth token (a dev pass throttling prod
   would show up here).

Deferred by design (rollout-watch items, not day-one): SIGHUP roster reload,
status-dashboard polish, `last-batch.json` crash-replay wiring.
