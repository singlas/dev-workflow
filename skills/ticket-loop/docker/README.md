# Containerized ticket-loop

Run each scheduled ticket-loop pass in a pinned Docker container on a Linux host,
on a systemd timer. The image bakes the **dev-workflow framework** (runner +
plugin) root-owned at `/opt/dev-workflow`; your repo checkout, auth, and secrets
live in a mounted volume. This is the unattended deployment — the interactive
`/loop /ticket-loop` and the laptop launchd variant (`../install-cron.sh`) are the
other two shapes.

> **Prereqs:** Docker on the host, a login user for the volume, and the framework
> checked out on the host to use as the build context. Everything below is one
> host at a time; secrets never enter the image or `docker inspect`.

## The three zones (boundary rule 2)

| Zone | What | Where |
|---|---|---|
| **Framework** (baked, root-owned) | runner (`cron-run.sh`, `run-pass.sh`, `loop-lock.sh`, `telegram.py`, `dw-config.py`), the plugin, `loop-mcp.json` | `/opt/dev-workflow` in the image |
| **Work tree + config** | your repo checkout (a `base_branch` clone) with its `dev-workflow.yml` at the root | the volume, at `@WORK_TREE@` (e.g. `/home/agent/<repo>`) |
| **Injected secrets/auth** | `agent.env`, `~/.claude` (auth), `state.json` | the volume, `@ENV_FILE@` + `/home/agent/.claude` |

The container runs as non-root `agent`; `/opt/dev-workflow` is root-owned, so a
build subagent physically cannot edit the framework driving it. A `git pull` of the
work tree can never change how the loop runs — only a rebuild can.

## 1. Build the image (pin the claude version)

Build context is the **framework repo root**, and the claude pin is required:

```
docker build -f skills/ticket-loop/docker/Dockerfile \
  --build-arg CLAUDE_CODE_VERSION=<pin> \
  -t <image>:<pin> <repo-root>
docker tag <image>:<pin> <image>:current
```

Verify `<pin>` against whatever `claude` your team runs — the autoupdater is off in
the image, so it stays put. Extend the Dockerfile's apt list to match your test
suite's system deps (it ships `git gh curl jq python3 python3-yaml postgresql-client`
+ `uv`).

## 2. Seed the volume (a base-branch clone of YOUR repo)

Create the volume and clone your repo's **base branch** into it at `@WORK_TREE@`,
owned by uid `10001` (the image's `agent` user):

```
docker volume create <volume>
docker run --rm -v <volume>:/home/agent node:22-bookworm-slim \
  bash -lc 'apt-get update && apt-get install -y git && \
    git clone --branch <base_branch> <your-repo-url> /home/agent/<repo>'
docker run --rm -v <volume>:/home/agent node:22-bookworm-slim \
  chown -R 10001:10001 /home/agent
```

`dev-workflow.yml` must exist at the checkout root (validate it first with
`python3 dev-workflow/validate.py dev-workflow.yml`).

## 3. Write `agent.env` on the volume (secrets — human only)

`agent.env` is **never read by Claude** — only the runner and the tracker MCP header
use it. Write it into the volume at `@ENV_FILE@` (mode `600`, owned by uid `10001`):

| Field | What |
|---|---|
| `LINEAR_API_KEY` | Tracker personal API key — the Linear MCP `Authorization: Bearer` value |
| `GH_TOKEN` | A PAT with contents + PR read/write on your repo (gh + git push) |
| `TELEGRAM_BOT_TOKEN` | The bot token (same bot as any laptop loop) |
| `AGENT_TELEGRAM_CHAT_ID` | The dedicated group's chat id |
| `CLAUDE_CODE_OAUTH_TOKEN` | From `claude setup-token` — auth without a browser (or `docker run -it … claude` once to `/login`; it persists in the volume) |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` | Optional — only if your test suite needs a DB |

```
docker run --rm -i -v <volume>:/home/agent node:22-bookworm-slim \
  bash -lc 'cat > /home/agent/agent.env && chmod 600 /home/agent/agent.env && \
    chown 10001:10001 /home/agent/agent.env' < ./agent.env.local
```

## 4. Render + install the units

The `agent.service.template` + `agent.timer.template` carry `@PLACEHOLDER@` tokens.
`sed` your names in and install to `/etc/systemd/system/`:

```
sed -e 's|@IMAGE@|<image>:current|' -e 's|@VOLUME@|<volume>|' \
    -e 's|@CONTAINER@|<name>-pass|' -e 's|@WORK_TREE@|/home/agent/<repo>|' \
    -e 's|@ENV_FILE@|/home/agent/agent.env|' -e 's|@ONCALENDAR@|*-*-* 09..20:00/30|' \
    skills/ticket-loop/docker/agent.service.template | sudo tee /etc/systemd/system/<name>.service
sed -e 's|@ONCALENDAR@|*-*-* 09..20:00/30|' \
    skills/ticket-loop/docker/agent.timer.template | sudo tee /etc/systemd/system/<name>.timer
sudo systemctl daemon-reload
sudo systemctl enable --now <name>.timer
```

The service passes `-e DW_WORK_TREE=@WORK_TREE@` and `-e DW_ENV_FILE=@ENV_FILE@`
only — the runner sources the secrets from the volume itself, so **no secret is
ever passed as unit-level env** (boundary rule 2: nothing sensitive in
`docker inspect`). Set the host timezone to your team's zone so `@ONCALENDAR@`
times match your working window.

## 5. Smoke-test (dry run)

`run-pass.sh` is the image CMD, but it's plain `CMD` (not `ENTRYPOINT`), so you can
override the command for a no-side-effects pass — no sends, no builds:

```
docker run --rm --network host \
  -e DW_WORK_TREE=/home/agent/<repo> \
  -v <volume>:/home/agent \
  <image>:current /opt/dev-workflow/bin/run-pass.sh --dry-run
```

Confirm the tracker MCP answered (static key works), `gh auth` is OK, and the
Telegram poll succeeded before enabling the timer.

## The `--plugin-dir` fallback

The runner invokes the baked plugin's skill as `/dev-workflow:ticket-loop` via
`--plugin-dir /opt/dev-workflow/plugin` **when the pinned `claude` supports
`--plugin-dir`**. If it doesn't, the runner logs a warning and falls back to a
repo-local `/ticket-loop` — so for that fallback to work, the work tree must also
carry the skill at `.claude/skills/ticket-loop/`. Newer claude builds make the
baked plugin the source of truth; the fallback is only for older pins.

## Operate

- Trigger a pass now: `sudo systemctl start <name>.service`
- Status: `systemctl list-timers <name>.timer` + `systemctl status <name>.service`
- Logs: `journalctl -u <name>.service`, plus the loop's own cron log at
  `<work_tree>/<state_dir>/logs/ticket-loop-cron.log` inside the volume
- Pause: `sudo systemctl disable --now <name>.timer`
