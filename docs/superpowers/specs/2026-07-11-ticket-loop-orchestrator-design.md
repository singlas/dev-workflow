# Central round-robin orchestrator for the ticket-loop

- **Date:** 2026-07-11
- **Status:** Design — Fable + Codex review incorporated; pending user sign-off, then implementation plan
- **Author:** Shashank (with Claude)

## Problem

The ticket-loop runner drives one project per deployment. We want a single
always-on box (the **nt** Niptao box — `ssh nt`, ap-south-1, t4g.large, ARM,
8 GiB + 2 GiB swap) to work **three** projects — niptao, paytunes-backend, and
rasa — each with its own repo, Linear board, and Telegram group, under **one
central scheduler** that round-robins them: run one project's pass to
completion, then move to the next, adapting the cadence to how much work each
board actually has, day and night.

The framework is already almost fully parameterized per-instance — every
per-tenant axis (`DW_WORK_TREE`, `dev-workflow.yml`, `TICKET_LOOP_STATE_DIR`,
per-file `agent.env`, `TICKET_LOOP_MCP_CONFIG`, `TICKET_LOOP_LABEL`) is an env
var or config value, and the singleton lock + Telegram offset are keyed to the
state dir, not global. So multi-project is **N instances of the existing
runner** driven by a new scheduler, not a re-architecture.

niptao **already runs this loop** (its `agent/nip-*`, `worktree-agent-*`,
`feature-a..d-*` branches are loop artifacts; it is the only repo with a
committed `dev-workflow.yml` + `.mcp.json`). So this is: **migrate niptao's
existing loop onto the orchestrator, and onboard paytunes-backend + rasa
alongside it.**

## Goals

1. One long-lived orchestrator process on nt that round-robins N projects
   **sequentially** (never two passes at once).
2. A **cheap pre-check** before each pass (tracker queue depth + open
   questions) so idle projects don't burn a full `claude -p` pass.
3. **Adaptive backoff**: idle projects lengthen their interval; work snaps them
   back to fast. This subsumes day/night — quiet nights back off automatically.
4. Run 24/7 (each project may still opt into a `schedule.window`).
5. Fit the existing infra conventions (Docker on nt, `--restart unless-stopped`,
   memory/cpu caps, arm64).

## Non-goals

- **Not** deprecating the cron/launchd/timer scheduler (see below).
- **Not** a shared Telegram group or shared bot — each project keeps its own
  group + bot (avoids the getUpdates offset-contention hazard).
- **Not** the isolated per-container shape — one orchestrator container holds
  all three work trees (chosen tradeoff; see §5). Isolated containers remain
  the documented upgrade path.
- No tracker adapter beyond Linear (the only implementation today).

## Four composable axes (do NOT bundle them)

> **Wording note (from review):** these are **composable**, not fully
> orthogonal. Mode and cadence share orchestrator-owned roster + backoff state;
> packaging leaks into behavior (container mode uses an external runner + a
> shared mounted secret volume, laptop mode assumes different path semantics).
> The point stands — don't hard-wire one axis to another — but "orthogonal"
> oversells the independence.


The orchestrator replaces the **scheduler**, not the **runner** — it shells out
to the same per-pass core (`run-pass.sh` → `cron-run.sh` → `claude -p
/ticket-loop`). Because of that, four choices are **independent** and the
framework must compose them, never hard-wire one to another:

| Axis | Options | Notes |
|---|---|---|
| **Mode** | single-project ↔ multi-project **orchestrator** | orchestrator = round-robin over a roster of N; single = today's one-instance runner. Both stay first-class. |
| **Cadence** | **fixed** ↔ **adaptive** (pre-check + backoff) | the "intelligent" logic. Fixed = calendar interval / constant gap. Applies to **both** modes. |
| **Packaging** | **bare** (launchd/systemd) ↔ **containerized** (docker) | orthogonal to mode: an orchestrator can run bare; a single instance can run in docker. |
| **Host** | **local/laptop** ↔ **nt box** (+ schedule window) | where and when it runs. |

Our target nt deployment is **one point** in this space —
`{orchestrator, adaptive, docker, nt}` — but the framework also supports, e.g.,
`{single, fixed, bare, local}` (today's laptop cron, unchanged),
`{orchestrator, adaptive, bare, local}` (a laptop round-robin, no docker), or
`{single, adaptive, docker, nt}` (one project, containerized, with the cheap
pre-check). The design below builds the **orchestrator (mode axis)** and the
**adaptive cadence (cadence axis)** as separable pieces; packaging and host are
deployment concerns handled by the install/runner layer, not the loop.

**Non-deprecation.** The existing single-project shapes — interactive
`/loop /ticket-loop`, cron/launchd/systemd timer (`install-cron.sh`), and the
containerized single-pass (`docker/` + timer) — all stay first-class. The
orchestrator is **additive on the mode axis**; deprecating single-project would
force a solo user to run a daemon for no gain.

**Cadence is not welded to mode.** The orchestrator supports **fixed** cadence
(constant per-project interval, no pre-check) as well as **adaptive**; and a
single-project runner can opt into the adaptive pre-check. Fixed-vs-adaptive is
a per-roster (and per-project override) setting, not a property of "being an
orchestrator."

**Migration caveat (deployment-specific, not framework):** when niptao folds
into the orchestrator, **decommission niptao's individual cron/launchd loop
job** — two schedulers must not drive one project (they'd fight over the board
+ Telegram offset). The per-project singleton lock prevents *concurrent* passes
but is a safety net, not a license to run both.

## The roster

| Project | Remote | Base branch | Loop today? | Onboarding |
|---|---|---|---|---|
| **niptao** | `Niptao/niptao` | `dev` → `main` | ✅ running | Fold in; dedicated work tree (§8) |
| **paytunes-backend** | `Paytunes/paytunes-backend` | `master` | ❌ | `dev-workflow.yml`, Linear map, TG group+bot, GH token |
| **rasa** | `singlas/rasa-landing-page` | `main` only | ❌ | Same + base/prod branch-model decision (single-branch repo) |

Linear board state: **one of {rasa, paytunes} has a board, one does not**
(per user). niptao is live regardless. The project without a board is on the
critical path for *its* onboarding, not for the orchestrator itself.

Three different GitHub owners (`Niptao`, `Paytunes`, `singlas`) → each project's
`agent.env` carries its own **fine-grained, per-repo** `GH_TOKEN`, plus its own
`LINEAR_API_KEY`, `TELEGRAM_BOT_TOKEN`, `AGENT_TELEGRAM_CHAT_ID`.

> **Do NOT use one PAT scoped to all three (review — §5).** All passes run
> `--dangerously-skip-permissions` as the same uid, so `600` perms are moot
> same-user; the real threat is **prompt injection** — malicious content in a
> Linear ticket or Telegram reply on project A exfiltrating B's token and
> pushing to B's org. A shared PAT turns one compromised board into write
> access everywhere. Minimal per-repo scopes cap the blast radius. Two of the
> three are companies; state the residual explicitly.

## Architecture (Approach A — thin orchestrator over the unchanged runner)

Considered and rejected:
- **B — 3 staggered timers, no central brain.** Fixed times, can overlap, no
  adaptive backoff, no "next starts when last finishes." This is what we moved
  away from.
- **C — full daemon + scheduler framework.** Overkill for 3 projects on one box.

### Components

**1. Roster config** — a new orchestrator-level `roster.yml` listing the N
projects; each entry: `name`, `work_tree`, `env_file`, `state_dir`, optional
`model`/`tz`/`window`. A roster-level `cadence: adaptive|fixed` (+ `interval`
for fixed) sets the default; each entry may override it (cadence axis). Distinct
from each repo's `dev-workflow.yml` (the per-repo contract, still read
per-pass). The orchestrator owns roster.yml; nothing about the per-repo config
changes.

**2. Orchestrator loop** — `skills/ticket-loop/orchestrator/orchestrator.sh`
plus a small stdlib-Python helper for scheduling state/math (matching the
`telegram.py` idiom). Long-lived (PID 1 in the container):

```
load roster + orch-state
loop forever:
  pick the next project whose next_eligible time has passed (round-robin order)
  if project has a schedule.window and now is outside it → skip, requeue
  pre-check (cheap, no full pass)
  if signal → run ONE full pass via run-pass.sh (exclusive), classify outcome
  update that project's backoff, persist orch-state
  short sleep, continue
```

**3. Cheap pre-check (the "intelligent" part).** Two free signals chosen to
avoid the Telegram offset hazard:
- **Tracker queue depth** — a tiny new `queue-count.py` (Linear GraphQL over
  `urllib`, keyed by the project's `LINEAR_API_KEY`, reading team/label/states
  from that repo's `dev-workflow.yml` `tracker.roles`). Belongs in the
  tracker-adapter seam. Returns count of eligible tickets; `>0` → run.
- **Open questions** — read the project's `state.json` `questions` map (free, no
  `getUpdates` call, no offset consumed). Non-empty → a human may have answered
  → run so the pass polls Telegram.

Neither present → skip cheaply, lengthen the interval. A "human poke unrelated
to an open question" is caught by the read-only getUpdates **peek** (Supervision
§7) — safe once the orchestrator is the sole consumer per bot.

**4. Adaptive backoff + night.** *(cadence axis = adaptive; the alternative is
**fixed** — a constant per-project interval with no pre-check and no ladder,
selected per roster or per project. §3 pre-check runs only in adaptive mode.)*
Per-project `orch-state.json`
`{dry_streak, next_eligible, last_pass}`. Ladder e.g. `10m → 20m → 40m → cap
60m`. A **productive** pass resets to `10m`; a **dry** pass advances the ladder.
Night needs no special mode — empty boards back off to the 60m floor on their
own. Projects run 24/7 by default; a repo's `dev-workflow.yml`
`schedule.window`, if set, gates that project (tighten-only).

*Outcome classification (revised after review — outer inference is too weak: it
misses triage/comment-only/branch-only work, and "queue count dropped" compares
counts not ticket-ID sets, so one-done + one-filed reads as dry).* **Drop the
"no skill changes" constraint** — the pass already knows what it did. The skill
emits one structured outcome line into the state dir (`{picked, pr_opened,
asked, blocked, error}`); the orchestrator reads it. Four classes, not two:
- **productive** (`pr_opened` or a ticket genuinely advanced) → reset to `10m`.
- **dry** (ran, nothing to do) → advance the ladder.
- **waiting-on-human** (`asked`/`blocked`, an open question outstanding) → a
  **separate fixed interval (15–20m)**, neither the dry ladder nor "productive."
  This stops an ignored question from either pinning the project at fast cadence
  or spamming 24 poll-passes/day. (Polling faster doesn't make humans answer
  faster.)
- **error** (non-zero exit, timeout kill, or the background-guillotine WARN
  `cron-run.sh` already emits) → increment a per-project error streak; escalate
  after N (see Supervision below). Never silently treated as dry.

**5. Secret scoping in the shared container.** Each pass is a child process that
sources **only** its own `agent.env` via `DW_ENV_FILE` (run-pass.sh already does
this). The orchestrator holds **no** project secrets in its own env; it passes
each child a minimal env + that project's `DW_ENV_FILE` / `DW_WORK_TREE` /
`TICKET_LOOP_STATE_DIR`. Residual risk (a build subagent for A reading B's
`agent.env` off disk, same `agent` user) is inherent to the one-container
choice — mitigated by `600` perms and single-owner trust (all three are the
user's projects). Isolated containers remain the upgrade path.

**6. Container + supervision.** Extend the existing `docker/Dockerfile`
(framework baked root-owned at `/opt`, boundary rule 2 intact); CMD becomes the
orchestrator instead of a one-shot pass. One mounted volume holds all three work
trees + three env files + three state dirs + `roster.yml` + `orch-state.json`.
On nt: `docker run -d --restart unless-stopped --network host --memory=2g
--cpus=<cap> --log-opt max-size=10m --log-opt max-file=3`. Builds arm64 (nt is
ARM; base images multi-arch). Crash → Docker restarts → orchestrator reloads
roster + orch-state and resumes.

**7. The per-project singleton lock stays** as the guard against an interactive
`/loop` session overlapping a pass. Cross-project serialization now comes free
from the orchestrator being single-threaded.

**8. niptao work-tree safety (CRITICAL).** The loop does `git fetch && git reset
--hard origin/<base>` on its work tree every pass — and also runs arbitrary bash
from `quality.bootstrap` and `hooks.pre_pass` in that tree. niptao's **live prod
checkout serves gunicorn** — the orchestrator's niptao work tree **must** be a
separate dedicated base-branch clone, never `/home/ubuntu/niptao`.

*Guard mechanism (revised after review — a path denylist is theatre; inside the
container the live checkout appears via a bind mount under an arbitrary path and
a `/home/ubuntu/niptao` string never matches):* use a **positive allowlist**.
Every roster work tree must (a) resolve under the orchestrator's own volume
root, **and** (b) carry a marker file `.dw-agent-clone` written at seed time.
The orchestrator refuses at startup any roster entry missing the marker or
outside the volume root. This whitelists orchestrator-owned clones instead of
trying to enumerate every prod path (symlinks, renamed roots, future layout
changes all defeat a denylist).

### Capacity

Sequential round-robin caps the loop's added load at **one** `claude -p` at a
time — but it does **not** serialize against niptao's *runtime* `claude -p`
celery bursts (the 6.3 GiB peak). Worst case: 6.3 GiB burst + a 2 GiB pass >
8 GiB physical → **host-wide** swap/reclaim, and the host OOM-killer may pick a
Django worker or prod's own claude. The container cap protects the box from the
pass; it does **not** protect prod from the overlap.

*Revised after review — the only mechanism that actually serializes against the
runtime bursts:* a **host-memory headroom gate in the pre-check**. Read
`/proc/meminfo` `MemAvailable`; if `< ~2.5 GiB`, skip this turn and requeue
(short delay, not a ladder advance). Plus hard container limits: `--memory=2g
--memory-swap=2g` (no extra swap beyond RAM), `--cpus=1` (2-vCPU box runs prod),
`--pids-limit` (fork protection), `--init` (reap zombies + signal handling).
Give niptao a conservative backoff floor. Watch the docker-mem sampler after
rollout. Sequential + the headroom gate + these caps are non-negotiable.

## Supervision & hardening (added after Fable + Codex review)

Approach A wraps the runner unchanged, which means it also **inherits the
obligation to re-implement what systemd/launchd gave the timer shapes for
free**. Both reviews found the scheduling logic sound and the supervision layer
absent. Required for unattended 24/7 operation:

1. **Per-pass timeout (blocker).** Wrap each pass in `timeout` (e.g. 90–120 min;
   the lock's own 2h staleness heuristic implies passes finish well under 2h).
   On expiry, kill the **process group**, classify **error**. Without this, one
   wedged pass (stuck MCP, network stall) freezes the whole single-threaded
   fleet indefinitely.

2. **Error class + escalation channel (blocker).** A non-zero/timeout/guillotine
   pass is an **error**, never "dry." Track a per-project **consecutive-error
   streak**; after N, escalate. The orchestrator needs its **own** Telegram
   destination (per-project errors → that project's group; orchestrator-level
   failures → a designated **ops group**). Note a shared failure mode: all three
   share one `~/.claude`, so an expired `CLAUDE_CODE_OAUTH_TOKEN` errors **all
   three at once** — escalate loudly.

3. **Crash write-ahead (blocker).** Persist `pass_started {project, ts}`
   **before** launching. On startup, an existing record = the container died
   mid-pass → count a crash for that project, advance its ladder / crash streak,
   and **skip it after k consecutive crashes**. Prevents an OOM-on-project-A →
   restart → re-pick-A crash loop that starves B and C and hammers the box.

4. **PID 1 discipline.** Run the container with `--init`; `orchestrator.sh`
   traps `SIGTERM` and **drains gracefully** (finish or timeout-kill the current
   pass, persist orch-state, exit) so `docker stop` doesn't SIGKILL a live
   `claude` mid-ticket (which would leave a dangling branch + an advanced
   Telegram offset).

5. **Lock-clear on boot.** The orchestrator is PID 1 and by construction no pass
   runs at its startup → **clear every roster project's `loop.lock`** on boot.
   Container PID namespaces reset to small numbers, so a stale `loop.lock/pid`
   can false-match a live PID and make every pass skip (silently, classified
   dry). Also: a pass that yields the lock to an interactive `/loop` session is
   **not** a dry pass — don't back the project off for being actively worked.

6. **Periodic unconditional safety pass.** `queue-count.py` re-implements ticket
   eligibility; any drift from the skill's real filter and the pre-check skips
   real work **forever, silently** (the dangerous failure direction). Mitigate
   two ways: derive both from **one source of truth** in the tracker-adapter
   seam, **and** force one full pass per project every 6–12h regardless of
   pre-check. Guarantees eventual progress.

7. **getUpdates peek closes the stranded-poke gap.** Once the orchestrator is
   the sole consumer per bot (niptao's cron decommissioned), the pre-check may
   do a read-only `getUpdates` **peek at the current offset without persisting
   it** — consumes nothing, safe by construction — to catch a human message on
   an idle project ("stop", "urgent: X") that isn't a reply-to and matches no
   ticket prefix. ~20 lines; supersedes the earlier YAGNI.

8. **Observability + control.** Extend `orch-state.json` with `current:
   {project, started_at}` (free from #3), `last_outcome`, `error_streak`. Emit
   **one decision line per turn to stdout** (project, pre-check result, outcome,
   next_eligible) so `docker logs` is the live dashboard. Extend the existing
   `ticket-loop status` subcommand to read orch-state. Add a control surface:
   run-now (touch-file trigger) and roster reload (SIGHUP).

9. **`window` precedence.** A roster entry's `window` and the repo's
   `dev-workflow.yml` `schedule.window` both gate — resolve to their
   **intersection** (tighten-only, consistent with boundary rule 1). A
   window-skip does **not** advance the backoff ladder.

10. **Sleep to `min(next_eligible)`** rather than a fixed short poll of the
    roster.

**Deferred to the rollout watch period (not blockers):** the full status
dashboard polish, SIGHUP reload, `last-batch.json` wiring, and a note on whether
niptao's runtime claude shares a rate-limit pool with the loop's OAuth token
(if so, a dev pass can throttle production — worth confirming).

## Data / control flow

```
orchestrator.sh (PID 1, one container)
  ├─ reads roster.yml (N projects)
  ├─ reads/writes orch-state.json (per-project backoff)
  ├─ per project turn:
  │    ├─ queue-count.py  ── Linear GraphQL (project's LINEAR_API_KEY) ─┐
  │    ├─ read state.json questions map (free)                          │→ run? 
  │    └─ if run: exec run-pass.sh with minimal env + DW_ENV_FILE/DW_WORK_TREE/STATE_DIR
  │           └─ run-pass.sh → cron-run.sh → loop-lock → claude -p /ticket-loop
  └─ classify outcome → update backoff → persist → next project
```

## Onboarding (the real critical path for rasa/paytunes)

The orchestrator is bounded new code. The loop is **tracker-driven**, so a new
project can't be round-robined until it has:
1. `dev-workflow.yml` at repo root (validated: `uv run dev-workflow/validate.py`).
2. A Linear team with `agent` / `agent-blocked` / exclude / done labels, and at
   least one eligible ticket.
3. A Telegram group + a dedicated bot (own `TELEGRAM_BOT_TOKEN` +
   `AGENT_TELEGRAM_CHAT_ID`).
4. `agent.env` (600) with `LINEAR_API_KEY`, `GH_TOKEN`, TG creds.
5. rasa only: decide the branch model (single-branch `main` → base = prod =
   `main`, feature PRs into `main`; or introduce a `dev` trunk).

## Rollout sequence (proposed)

1. Build the orchestrator with the **supervision blockers included from day one**
   (per-pass timeout, error class + escalation channel, crash write-ahead,
   `--init`/SIGTERM drain, lock-clear-on-boot, host-memory headroom gate, the
   marker-file work-tree guard). These are not "phase 2" — they're what makes an
   unattended loop safe.
2. Run against **niptao only** (already onboarded) — prove round-robin-of-one +
   the four-class backoff + the guard + the memory gate on nt.
3. Decommission niptao's individual cron/launchd loop job.
4. Onboard whichever of {rasa, paytunes} has a Linear board → add to roster
   (fine-grained per-repo PAT, own bot + group).
5. Onboard the remaining one once its board exists.

## Open questions / risks

- **Outcome classification** now comes from a skill-emitted structured line
  (§4), not outer inference — lower misclassification risk, but requires the
  small skill change. Refine the class rules from logs during rollout.
- **orch-state.json corruption** on crash mid-write → atomic temp-file-rename
  (same pattern as `telegram.py` `save_state()`); write-ahead record per §
  Supervision-3.
- **niptao capacity** overlap — the host-memory headroom gate (§Capacity) is the
  primary mitigation; watch the docker-mem sampler after rollout.
- **Prompt-injection across three orgs** — per-repo fine-grained PATs cap it; the
  hard firewall (isolated-container shape) stays the upgrade path.
- **Rate-limit pool** — confirm whether niptao's runtime `claude -p` shares an
  account/rate-limit pool with the loop's OAuth token (a dev pass could throttle
  prod). One sentence to verify at rollout.

## Amendments (2026-07-13, from first-week production data)

- **Pre-check questions-signal removed.** Field data (23 `waiting` outcomes/day,
  ~43M cache-read tokens) showed "open questions → run the pass, a human may
  have answered" burns a full claude pass every `waiting_interval` for as long
  as a question sits unanswered — and it is redundant: an answer IS an
  unconsumed update, which the read-only `peek` already detects precisely. The
  pre-check is now queue-count + peek only; an unanswered question costs zero
  passes until the human replies (8h forced-full remains the drift backstop).
- **`orch.env` + shared default bot.** Orchestrator-level config
  (`ORCH_TELEGRAM_*`, `DEFAULT_TELEGRAM_BOT_TOKEN`) moved from `docker run -e`
  into `<roster dir>/orch.env`. Projects without their own `TELEGRAM_BOT_TOKEN`
  get the default bot injected in **shared (no-ack) mode**: `telegram.py` never
  sends a getUpdates offset (an offset acks bot-wide and would destroy sibling
  projects' pending messages) and filters on chat id + a local floor instead.
  Constraints: Telegram's 24h update retention (unchanged vs the acked flow)
  and a 100-unacked-update scan window — dedicated bots stay first-class for
  busy groups. New-tenant chat setup shrinks to: create group, add default bot,
  record `AGENT_TELEGRAM_CHAT_ID`.
- **BotFather group-privacy gotcha** (bit rasa on day 2): default privacy ON
  delivers only /commands and replies-to-bot; plain `"RAS-5 go"` answers never
  reach the bot. Runbook now mandates /setprivacy Disable (or bot-as-admin).
