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
pre-check (adaptive)    → queue-count.py (Linear depth) + telegram.py peek
                          (read-only) — both idle? back off. Open questions are
                          NOT a signal: an answer IS a pending message the peek
                          sees, so an unanswered question costs zero passes
                          (the 8h forced-full pass is the drift backstop)
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

## Deployment runbook (docker — field-tested on nt, 2026-07-12)

Everything below can be staged while any existing single-project scheduler
keeps running; only step 9 (cutover) touches the live loop.

### 1. Build the image

The claude pin is **whatever `claude --version` prints on the machine your
team runs** — there is deliberately no pin file to look up (the Dockerfile
errors without an explicit pin so version drift is always a conscious act).
Tag the image with the pin so `docker images` self-documents what's deployed:

    git clone https://github.com/singlas/dev-workflow.git ~/dev-workflow && cd ~/dev-workflow
    CLAUDE_PIN=2.1.207 IMAGE=dw-agent:2.1.207 VOLUME=dw-agent \
      skills/ticket-loop/docker/local-run.sh build

`IMAGE` and `VOLUME` are arbitrary names read by every `local-run.sh`
subcommand — **use the same values in every command that follows**, including
the final `docker run`. Mixing names mid-runbook puts your seed in volume A
while the orchestrator mounts empty volume B.

### 2. One-time volume-root ownership fix

The first `seed` creates the volume with `/home/agent` itself owned by root
(the seed helper only chowns what it clones). The `agent` user (uid 10001)
must own the top directory or roster writes and the orchestrator's own
`orch/`/`state/` mkdirs fail with `Permission denied`:

    docker run --rm --user root -v dw-agent:/home/agent dw-agent:<pin> \
      bash -c 'chown 10001:10001 /home/agent'

### 3. Seed each project's dedicated clone

NEVER point a roster entry at a live/prod checkout: every pass runs
`git reset --hard origin/<base>` plus the repo's bootstrap/pre-pass hooks in
that tree. The marker + volume-root allowlist makes the orchestrator refuse
anything else at startup. `seed` writes the `.dw-agent-clone` marker for you.

The seed container has no SSH agent, so private repos clone over HTTPS with
the project's PAT embedded once, then scrub it (passes re-authenticate every
time via `gh auth setup-git` + the `GH_TOKEN` in the env file):

    VOLUME=dw-agent IMAGE=dw-agent:<pin> skills/ticket-loop/docker/local-run.sh seed \
      "https://x-access-token:<PAT>@github.com/<org>/<repo>.git" <base-branch> <name>
    docker run --rm -v dw-agent:/home/agent dw-agent:<pin> \
      bash -c "cd /home/agent/<name> && git remote set-url origin https://github.com/<org>/<repo>.git"

### 4. Secrets: TWO env files per project

Keep master copies in the framework clone's `.local/` (gitignored — the
designated per-machine secrets spot; `chmod 600` them). A bare `.env` at this
repo's root is **not** ignored — don't use it.

**(a) Loop secrets** → `/home/agent/<project>.env`, sourced by `run-pass.sh`
into the pass environment. Minimum contents:

    LINEAR_API_KEY=…            # tracker MCP header + queue-count pre-check
    GH_TOKEN=…                  # fine-grained per-repo PAT (see onboarding §PAT)
    AGENT_TELEGRAM_CHAT_ID=…    # this project's own group (always per-project)
    TELEGRAM_BOT_TOKEN=…        # OPTIONAL: a dedicated bot. Omit it and the
                                # orchestrator injects DEFAULT_TELEGRAM_BOT_TOKEN
                                # from orch.env in shared (no-ack) mode — a new
                                # tenant then needs only a group + chat id
    CLAUDE_CODE_OAUTH_TOKEN=…   # from `claude setup-token` — headless auth, no login
    # only if the repo's test suite needs a DB (see step 5):
    DATABASE_URL=postgres://<project>_agent:<pw>@127.0.0.1:5432/<project>_agent
    PGHOST=127.0.0.1
    PGUSER=<project>_agent
    PGPASSWORD=<pw>
    PGDATABASE=<project>_agent

Load with a full replace (`put-env` truncates, never appends — but it only
writes `/home/agent/agent.env`; for additional projects use the `cat >` form):

    VOLUME=dw-agent skills/ticket-loop/docker/local-run.sh put-env .local/<project>-agent.env
    # or, for any path/name:
    docker run --rm -i --user root -v dw-agent:/home/agent dw-agent:<pin> bash -c \
      'cat > /home/agent/<project>.env && chown 10001:10001 /home/agent/<project>.env && chmod 600 /home/agent/<project>.env' \
      < .local/<project>-agent.env

**(b) App env** (only if the target repo's settings read a `.env` — e.g. a
Django repo with `environ.read_env`) → `<work_tree>/.env` inside the volume,
same `cat >` command. Untracked files survive the per-pass
`git reset --hard`, so it persists. Keep the app's third-party keys (AWS,
payment, LLM, …) HERE and not in the loop env: whatever is in the loop env is
exported into the claude pass's shell (`printenv`-visible to the agent);
app-env keys materialize only inside the app's own processes.

Precedence when a key exists in both: the loop env wins — `run-pass.sh`
exports it first, and dotenv loaders (django-environ et al.) don't overwrite
existing environment variables. Keep `DATABASE_URL` only in the loop env
(one source of truth; the shell-level `PG*` copies are what the test
wrapper's `psql`/`dropdb` helpers need).

### 5. DB fence (if the repo's tests hit a database)

Give the agent a **scoped role that cannot reach the prod database even in
principle** — prompt-injected or buggy test code must hit a wall of
configuration, not hope. `CREATEDB` is needed where the test runner
creates/drops its own test databases (Django):

    sudo -u postgres psql <<'SQL'
    CREATE ROLE <project>_agent LOGIN PASSWORD '<generated>' CREATEDB;
    CREATE DATABASE <project>_agent OWNER <project>_agent;
    REVOKE CONNECT ON DATABASE <prod_db> FROM PUBLIC;   -- PUBLIC has connect by default!
    GRANT  CONNECT ON DATABASE <prod_db> TO <prod_role>;
    SQL

Verify from inside the container (`--network host` matters):

    docker run --rm --network host -v dw-agent:/home/agent dw-agent:<pin> \
      bash -c 'set -a; . /home/agent/<project>.env; set +a; psql "$DATABASE_URL" -c "select 1"'

### 6. Broker fence (if the repo uses celery/redis)

Under `--network host`, `localhost:6379` inside a pass **is the host's prod
redis**. Tests don't need a broker (eager mode), but a stray non-eager
`.delay()` would enqueue into prod's queue and a prod worker would execute
it. Point the agent's APP env (the work-tree `.env`) at an in-process
transport so a stray publish evaporates instead:

    CELERY_BROKER_URL=memory://
    CELERY_RESULT_BACKEND=cache+memory://

### 7. Validate before cutover (old scheduler still running — safe)

    # one --dry-run pass: no sends, no builds; proves clone/config/MCP/gh/claude auth
    VOLUME=dw-agent IMAGE=dw-agent:<pin> skills/ticket-loop/docker/local-run.sh dry-run <name>
    # the pass logs to a FILE, not stdout — quiet terminal is normal; read the verdict:
    docker run --rm -v dw-agent:/home/agent dw-agent:<pin> bash -c \
      'tail -40 /home/agent/<name>/.agent-loop/logs/ticket-loop-cron.log; cat /home/agent/<name>/.agent-loop/outcome.json'

    # one warm-up test run: proves the quality gate + DB fence end to end, and
    # warms uv's cache + the keepdb test database so real build passes start fast
    docker run --rm --network host -v dw-agent:/home/agent dw-agent:<pin> \
      bash -c 'cd /home/agent/<name> && set -a; . /home/agent/<project>.env; set +a; <quality.test command>'

"Using existing test database …" on later runs is `--keepdb` working, not a
problem.

### 8. Host firewall (uid-owner rules — no prod service changes)

With `--network host` the container shares the host network namespace, so
per-container rules are impossible — but every pass runs as uid 10001, and
iptables matches on owner. Allow DNS (systemd-resolved lives on lo!) and
Postgres, reject the rest of loopback (redis, gunicorn, anything future),
block the EC2 metadata endpoint, leave the internet open (GitHub / Linear /
Telegram / Anthropic are the loop's job):

    id 10001    # expect "no such user" — the uid must be only the container's
    sudo iptables -A OUTPUT -o lo -p udp --dport 53   -m owner --uid-owner 10001 -j ACCEPT
    sudo iptables -A OUTPUT -o lo -p tcp --dport 53   -m owner --uid-owner 10001 -j ACCEPT
    sudo iptables -A OUTPUT -o lo -p tcp --dport 5432 -m owner --uid-owner 10001 -j ACCEPT
    sudo iptables -A OUTPUT -o lo                     -m owner --uid-owner 10001 -j REJECT
    sudo iptables -A OUTPUT -d 169.254.169.254        -m owner --uid-owner 10001 -j REJECT
    sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save

    # verify from inside the running container:
    docker exec dw-orchestrator bash -c 'timeout 3 bash -c "</dev/tcp/127.0.0.1/5432" && echo PG-OK || echo PG-BLOCKED'
    docker exec dw-orchestrator bash -c 'timeout 3 bash -c "</dev/tcp/127.0.0.1/6379" && echo REDIS-REACHABLE || echo REDIS-BLOCKED'
    docker exec dw-orchestrator bash -c 'curl -sS -m 5 https://api.github.com >/dev/null && echo NET-OK || echo NET-BROKEN'
    docker exec dw-orchestrator bash -c 'curl -s -m 3 http://169.254.169.254/ >/dev/null && echo IMDS-REACHABLE || echo IMDS-BLOCKED'

(The cleaner end-state is bridge networking — loopback services unreachable by
construction, IMDS blocked by its hop limit — at the cost of opening Postgres
to the docker subnet and a prod Postgres restart. A watch-week upgrade, not a
day-one requirement.)

### 9. Cutover — this exact order

    # a) on the OLD machine: stop its scheduler — freezes the Telegram offset
    skills/ticket-loop/install-cron.sh --uninstall && launchctl list | grep -i ticket  # expect empty
    # b) copy the project's live state.json (offset, open questions, digest stamps)
    ssh <box> 'docker run --rm -i --user root -v dw-agent:/home/agent dw-agent:<pin> bash -c \
      "mkdir -p /home/agent/state/<name> && cat > /home/agent/state/<name>/state.json && chown -R 10001:10001 /home/agent/state"' \
      < <old-work-tree>/.agent-loop/state.json
    # c) start the orchestrator (next section)

(a) before (b) or the offset moves after you copy it; skipping (b) entirely
means the first poll re-drains up to 24h of old group messages as new. Two
schedulers must never drive one project — the singleton lock is a safety net,
not a license.

### 10. Orchestrator env file + run + watch

The orchestrator's own (non-project) config lives in `orch.env` next to the
roster on the volume — no `-e` flags in `docker run`, nothing secret in
`docker inspect`. Master copy in `.local/orch.env`, same `cat >` push as §4:

    ORCH_TELEGRAM_BOT_TOKEN=…      # ops alert channel (🚨 escalations)
    ORCH_TELEGRAM_CHAT_ID=…
    DEFAULT_TELEGRAM_BOT_TOKEN=…   # shared fallback bot for tenants without
                                   # their own (see onboarding §3)

    docker run --rm -i --user root -v dw-agent:/home/agent dw-agent:<pin> bash -c \
      'cat > /home/agent/orch.env && chown 10001:10001 /home/agent/orch.env && chmod 600 /home/agent/orch.env' \
      < .local/orch.env

    docker run -d --name dw-orchestrator \
      --restart unless-stopped --init \
      --network host \
      --memory=2g --memory-swap=2g --cpus=1 --pids-limit 512 \
      --stop-timeout 5460 \
      --log-opt max-size=10m --log-opt max-file=3 \
      -v dw-agent:/home/agent \
      dw-agent:<pin> /opt/dev-workflow/bin/orchestrator.sh

Notes:
- All caps are non-negotiable on a shared prod box (see the spec's Capacity
  section). `--memory-swap` == `--memory`: no extra swap beyond RAM.
- `--init` + the SIGTERM drain: `docker stop` lets the current pass finish or
  hit its timeout — hence the generous `--stop-timeout` (> pass_timeout).
- Legacy `-e ORCH_TELEGRAM_*` flags still work and win over `orch.env`;
  per-project secrets stay in the per-project env files, sourced by each pass.
- `docker logs -f dw-orchestrator` is the live dashboard (one line per turn) —
  it goes QUIET for minutes while a pass runs; the pass detail streams to
  `/home/agent/state/<name>/logs/ticket-loop-cron.log` instead:
  `docker exec dw-orchestrator tail -f /home/agent/state/<name>/logs/ticket-loop-cron.log`
- The first turn per project is a **forced-full pass** (no pre-check) — by
  design, it proves the pipeline. A healthy first turn ends with the
  `classify <name>: …` + `turn <name>: outcome=… next_eligible=…` pair.
- Status table: `docker exec dw-orchestrator python3 /opt/dev-workflow/bin/orch.py \
    status --roster /home/agent/roster.yml --state /home/agent/orch/orch-state.json`
- Run one project now: `docker exec dw-orchestrator \
    bash -c 'echo <name> > /home/agent/orch/run-now'`
- `setlocale: LC_ALL` warnings in pass logs are cosmetic on images built
  before the `ENV LANG=C.UTF-8` Dockerfile fix — gone on the next rebuild.

## Onboarding a new roster project (checklist)

The loop is tracker-driven; a project can't be round-robined until it has:

1. `dev-workflow.yml` at its repo root (validate: `uv run dev-workflow/validate.py <file>`).
2. A Linear team with the queue/blocked/exclude/done roles mapped in
   `tracker.roles`, and at least one eligible ticket.
3. A Telegram **group of its own** (chat ids are always per-project) and a bot
   that can read it. Never point two ROSTER projects at one *group*, and never
   share a bot that anything outside this orchestrator also polls.

   **Which bot?**
   - **Shared default (the easy path):** with `DEFAULT_TELEGRAM_BOT_TOKEN` set
     in `orch.env`, a project needs no bot of its own — leave `TELEGRAM_BOT_TOKEN`
     out of its env file, add the default bot to the new group, set
     `AGENT_TELEGRAM_CHAT_ID`, done. The orchestrator injects the shared bot in
     **no-ack mode** (`telegram.py` never sends a getUpdates offset — a shared
     stream acked by one project deletes the siblings' pending messages; it
     filters by chat id + a local floor instead). Trade-off: no-ack mode scans
     only Telegram's first ~100 unacked updates and Telegram retains updates
     ~24h, so this is right for low-traffic groups, not busy ones.
   - **Dedicated (`TELEGRAM_BOT_TOKEN` in the project's env file):** the project
     owns the bot's whole getUpdates queue, so it acks normally — no scan-window
     limit. Use this for a high-traffic group, or any bot already used elsewhere.

   **Creating a bot (do the privacy step BEFORE adding it to any group):**
   1. BotFather → `/newbot` → name it → copy the token.
   2. **Turn privacy OFF — this is not optional.** BotFather → `/setprivacy` →
      pick the bot → **Disable**. With privacy ON (the default) a bot in a group
      receives ONLY `/commands` and *replies to its own messages*, so a plain
      `"RAS-5 go"` answer never reaches it and every pass classifies `waiting`
      forever. (Alternative to disabling privacy: make the bot a group **admin** —
      admins always see all messages. Do one or the other.)
   3. NOW add the bot to the group. (If you added it before step 2, Telegram
      caches the privacy state — remove it and re-add, or promote it to admin.)
   4. Get the chat id: send one message in the group, then run
      `python3 skills/ticket-loop/telegram.py discover` with the bot's token in
      env. Group ids are negative; supergroups start with `-100`.

   **Verify a bot can actually read its group** (catches the privacy trap before
   it costs you a night): send a NON-reply, non-command message in the group,
   then `curl -s "https://api.telegram.org/bot<token>/getUpdates?timeout=0"` — you
   should see that message. Empty result + `pending_update_count: 0` from
   `getWebhookInfo` = privacy is still on (or the bot isn't in the group). The
   silent-failure signature in production: answers show ✓✓ in Telegram, the
   project's `state.json` `offset` stays `0`, passes keep classifying `waiting`.
4. **A fine-grained per-repo `GH_TOKEN`.** Gotchas learned the hard way:
   - The token page's *Resource owner* dropdown only lists orgs that have
     **enabled** fine-grained PATs — flip it first at
     `github.com/organizations/<org>/settings/personal-access-tokens`
     (org admin; repeat per org as you onboard its projects).
   - Permissions: Contents R/W, Pull requests R/W, Checks R, Commit
     statuses R. NOT Workflows (`.github/workflows/**` is off-limits to the
     loop by design).
   - One PAT across orgs is a prompt-injection blast-radius mistake — a
     malicious ticket on project A must not be able to push to project B's
     org. Never substitute your personal account token (`gh auth token`) for
     the runtime `GH_TOKEN`: it's write access to everything you can touch.
   - (Residual risk in the one-container shape: passes run as one uid, so
     B's env file is readable from A's build subagent — accepted for
     single-owner rosters; isolated-per-container is the upgrade path.)
5. The two env files (runbook §4), the DB fence if its tests need one (§5),
   the broker fence if it uses celery (§6).
6. A dedicated clone on the volume + marker (§3), then append the roster entry:

       docker run --rm -v dw-agent:/home/agent dw-agent:<pin> cat /home/agent/roster.yml   # current
       # append via the same `cat >` full-rewrite used in §4, then:
       docker restart dw-orchestrator    # picks up the roster; drains first (SIGTERM)

   Restart is the supported reload path (SIGHUP reload is deliberately
   deferred); boot lock-clear + crash recovery make it safe at any time.
7. Dry-run the new project (§7) before trusting its first live turn.

## Rollout sequence (proven on nt)

1. Deploy with **one project** in the roster; watch several days of decision
   lines (four-class outcomes, ladder behavior, the memory gate under the
   host's own load spikes, `docker stats` on the container).
2. **Decommission that project's individual cron/launchd job at cutover**
   (runbook §9) — never before staging, never after starting the orchestrator.
3. Add the next project once its checklist is green; repeat.
4. Confirm during the watch period whether the host's own `claude` workloads
   share a rate-limit pool with the loop's OAuth token (a dev pass throttling
   prod would show up here).

Watch-week signatures worth escalating: an `error` classification whose pass
log segment looks clean; `outcome=dry` while the board visibly has queued
tickets; the memory gate never firing despite host memory pressure.

Deferred by design (rollout-watch items, not day-one): SIGHUP roster reload,
status-dashboard polish, `last-batch.json` crash-replay wiring, bridge-network
migration, trimming app env files to test-only values.
