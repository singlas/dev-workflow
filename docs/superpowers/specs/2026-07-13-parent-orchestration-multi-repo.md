# Parent orchestration: one product, many repos, one board, one group

**Status:** Phase 0 GO (2026-07-13) — the load-bearing unknown is PROVEN (§17);
proceed to Phase 1. Codex's other findings (§16) stand as required engineering,
not blockers. **Date:** 2026-07-13. **Target:** a 5.x minor.
**Depends on:** `tracker.project` (v0.5.1/0.5.2), `DEFAULT_CLAUDE_CODE_OAUTH_TOKEN`
+ `DEFAULT_TELEGRAM_BOT_TOKEN` (orch.env), the existing subagent-implementation
pattern in `skills/ticket-loop/SKILL.md`.

## 1. Problem

A product (paytunes: ~5 repos) or a personal umbrella (rasa: `rasa-landing-page`
+ `dev-workflow`) needs ONE agent working ONE Linear team and talking in ONE
Telegram group, while the actual code changes land in the RIGHT repo. Two shapes
we already rejected, with the reason:

- **N roster entries, one per repo, N Telegram groups** — fragments the human's
  context across groups. The user explicitly rejected this.
- **N roster entries sharing ONE group (flat)** — Codex demolished it: unsolicited
  messages (`bug:`, `take PAY-123`, `flag:`, scout approvals) carry no repo
  binding, so whichever repo polls next mutates its own project. Wrong repo gets
  the message, by construction (not an edge case).

The winning shape: a **thin parent** that owns the management plane and resolves
every inbound message to a target repo BEFORE any mutation, then delegates the
build. This is exactly Codex's prescription ("a dedicated broker that resolves a
target repo before any mutation").

## 2. The two planes

**Management plane — the parent (one roster entry per product).** Owns: the
Linear team, the one Telegram bot + group, the board view, questions/digest/scout,
PR-babysitting across children, and the routing decision. Also the home for
shared/general docs (read once, not duplicated per repo). Holds the child clones
as gitignored subfolders.

**Execution plane — the child repos.** Each keeps its own `dev-workflow.yml`
(quality gate, `base_branch`, `tracker.project`). A ticket is implemented here:
work tree, tests, PR — per repo. A child repo remains independently valid: a
developer can run the interactive skills in it directly (project-scoped since
0.5.2) with no parent involved.

## 3. Skill architecture (NEW skill; old one untouched)

- **`ticket-loop` (existing) — frozen.** Single-repo passes. Its 0.5.2
  `tracker.project` scoping stays valid for a lone child repo or a per-repo entry.
- **`ticket-loop-parent` (new).** The management plane. Selected by config, not
  code.
- **The build is a subagent, not a skill.** The existing loop ALREADY implements
  via a subagent in an isolated worktree; the parent reuses that pattern. No
  `build-ticket` skill, no `--build-only` flag — the execution primitive is a
  subagent task brief (§6). This is why the old skill is untouched.

**Selector (the seam already exists).** `cron-run.sh:187` resolves
`INVOKE="${DW_SKILL_INVOCATION:-/ticket-loop}"`. Add `agent.skill` to
`dev-workflow.yml` (validated in the existing `agent:` section); the runner passes
it through as `DW_SKILL_INVOCATION`. Single-repo repos say nothing → `/ticket-loop`
as today. The paytunes parent's `dev-workflow.yml` says
`agent: { skill: ticket-loop-parent }`.

## 4. Parent config shape

The parent repo root carries a `dev-workflow.yml` with the team, the parent skill,
and a `repos:` map. Children keep their own `dev-workflow.yml` (quality/branch);
the parent map is just project → clone path (+ url for seeding).

```yaml
# paytunes-parent/dev-workflow.yml
tracker:
  provider: linear
  team: Paytunes
  ticket_prefix: PAY
  # NO tracker.project here — the parent counts/reads the WHOLE team; per-repo
  # scoping lives in each child's dev-workflow.yml.
chat:
  provider: telegram        # ONE bot + group; parent is the sole consumer → acks normally
agent:
  skill: ticket-loop-parent
  enabled: true
repos:
  - { project: pt-api, path: pt-api, url: https://github.com/Paytunes/pt-api.git }
  - { project: pt-web, path: pt-web, url: https://github.com/Paytunes/pt-web.git }
  # …3 more
```

Layout on the volume:

```
/home/agent/paytunes/            # parent repo = the roster entry's work_tree
  dev-workflow.yml               # team + agent.skill + repos map
  docs/                          # shared PM/architecture docs (read once)
  .agent-loop/                   # PARENT state only: telegram offset+questions, digest stamps
  pt-api/   (gitignored, .dw-agent-clone, own dev-workflow.yml tracker.project: pt-api)
  pt-web/   (gitignored, .dw-agent-clone, own dev-workflow.yml tracker.project: pt-web)
  …
```

## 5. Message → repo resolution (the one genuinely new rule)

Every inbound Telegram message resolves to a target repo BEFORE any tracker
mutation:

- **Reply to a bot question** → routes by `message_id` (the parent's questions map
  records ticket → project → repo when it asked). Already how answers match.
- **`take PAY-123` / green-light an existing ticket** → read the ticket, route by
  its Linear project field.
- **`bug:` / `feature:` / `ticket:` / `flag:` (fresh, no ticket yet)** → the repo
  is ambiguous. Resolve by: (a) an explicit project tag in the message
  (`bug: [pt-api] checkout fails`), else (b) ask ONE clarifying question in the
  group ("which project — pt-api / pt-web / …?") and create only after the answer.
  NEVER create in a guessed project.
- **Scout proposals** the parent generates already carry the project (the parent
  scoped the scout per repo), so approvals route cleanly.

## 6. The build subagent contract

After the parent picks the next actionable ticket and resolves its repo, it:

1. Resets + bootstraps that child clone (parent's job, so the subagent starts
   clean — the parent repo itself is NEVER `git reset --hard`; only the child
   clone is).
2. Spawns a subagent with a task brief (a file, per subagent-driven-development):
   - **Work tree:** `/home/agent/paytunes/pt-api` (the resolved child clone).
   - **Task:** implement `PAY-123` (title/description/acceptance inline).
   - **Contract:** read THIS repo's `dev-workflow.yml` for `quality.test` /
     `quality.lint` / `repo.base_branch`; branch `feature-N`; open ONE PR into the
     child's base branch; obey the child's guardrails/diff budget.
   - **Return:** the PR URL + a one-line status. NOTHING to Telegram/board — the
     parent owns all human comms.
3. The parent records the PR (per project), comments/links on the ticket, and
   moves state per the tracker roles.

Subagent does purely code. Parent does purely PM. Clean split, proven pattern.

## 7. State model (why Codex's D/E collisions don't happen here)

No shared state dir. Two disjoint state homes:

- **Parent PM state** — `<parent>/.agent-loop/state.json`: telegram offset +
  questions map + digest/scout/hygiene stamps. The parent is the SOLE writer.
- **Per-child execution state** — each child clone's own `.agent-loop` for any
  build-local scratch; the child's `loop.lock` guards its own reset/build.

Because the planes never share a state dir, the "split state.json" refactor Codex
flagged is unnecessary — the split is by design, not by carving one directory.
The orchestrator's per-name backoff (`orch-state.json`) already keys on the ONE
parent entry name.

## 8. Telegram: acking, not no-ack

The parent is the sole consumer of its dedicated bot + group, so it uses the
NORMAL offset-acking `poll` (not shared no-ack mode). This removes the no-ack
100-unacked-update / 24h ceiling Codex flagged — that ceiling only exists to let
multiple projects share one bot across DIFFERENT groups. One product = one bot =
one consumer = normal acking. `DEFAULT_TELEGRAM_BOT_TOKEN` (no-ack) stays for the
OTHER shape (single-repo tenants sharing a default bot, one group each).

## 9. Claude token

The parent is one roster entry → one env file → one `CLAUDE_CODE_OAUTH_TOKEN` for
the whole product (all its child builds run on the product's account). Granularity
= per product, which is the right billing/limit unit. `DEFAULT_CLAUDE_CODE_OAUTH_TOKEN`
(orch.env, shipped) still provides the box-wide baseline. Per-child tokens inside
a product are explicitly out of scope (§12).

## 10. Pre-check + scheduling

- `queue_count` for the parent runs **team-wide** (no `tracker.project`) — it
  counts the whole product's actionable tickets, exactly the default behavior. If
  > 0, the parent runs and internally picks + routes one ticket.
- Round-robin is across ROSTER ENTRIES as today (niptao, rasa-parent,
  paytunes-parent). WITHIN a parent entry, the parent itself round-robins over its
  child `repos:` (see Q2, DECIDED): each pass drains+routes the shared group
  globally, then works ONE child repo (its PRs + its next ticket). "One repo per
  pass, next pass a different repo" is the child round-robin, not ticket priority.
- `cap_per_pass` (≤2) applies within a pass; keep a pass to ONE child repo (pick
  the top ticket, drain up to the cap in that same repo) so no pass switches work
  trees mid-flight.

## 11. Constraints (unchanged, restated)

- **1 ticket = 1 repo.** Hard rule. No cross-repo tickets/PRs. Rules out the hard
  case we parked.
- **Same-org fine-grained PAT.** All of a product's repos in one GitHub org (one
  PAT scoped to exactly them). Cross-org = separate products.
- **One orchestrator process.** No orchestrator-level singleton lock exists
  (Codex [A]); the single-process assumption holds as today.

## 12. Out of scope (explicit)

- Cross-repo tickets (one ticket touching 2 repos) — parked; the 1-ticket-1-repo
  rule forbids it.
- Per-child-repo Claude tokens inside a product — per-product only.
- Telegram crash-replay wiring (Codex [F2]) — pre-existing gap, localized to the
  parent's single consumer, no worse than niptao today; a separate follow-up.
- Migrating the live Linear teams/projects — a data migration done after this
  ships.

## 13. How this answers Codex's review of the flat shared-group design

| Codex finding (flat shared group) | Parent model |
|---|---|
| [F1] wrong repo gets the message (default) | §5 — parent resolves repo before any mutation |
| [D]/[E] shared state / lock collision | §7 — planes never share a state dir; no refactor |
| [F3] no-ack 100-update / 24h ceiling | §8 — parent is sole consumer → normal acking, ceiling gone |
| [F2] crash-replay gap | §12 — localized to one consumer; deferred, no worse than today |
| [A] no orchestrator singleton lock | §11 — orthogonal; one-process assumption unchanged |

## 14. Build plan (phases)

1. **Selector plumbing.** `agent.skill` in the schema + `cron-run.sh` passing it as
   `DW_SKILL_INVOCATION`; roster entry may also set it. Tests. (small)
2. **`ticket-loop-parent` skill.** PM loop (telegram/board/questions/digest at the
   parent) + resolve-repo (§5) + reset child clone + dispatch build subagent (§6)
   + record PR/state + PR-babysitting across children. (the bulk)
3. **Parent config** (`repos:` map) validation + a `dev-workflow.yml` example +
   docs. Seed helper: clone each `repos[].url` into `<parent>/<path>` with marker.
4. **Onboarding docs** for the parent shape; wire into the orchestrator runbook.

## 15. Open questions

- **Q1.** Does the parent repo need its OWN `.dw-agent-clone` marker + root
  allowlist entry, given it is never `git reset --hard`? Proposal: yes for the
  allowlist, but the parent skill must NOT reset it — only child clones reset.
  Confirm the work-tree guard treats a parent entry correctly.
- **Q2. DECIDED (repo-scoped).** PR-babysitting is scoped to the CURRENT PASS's
  repo only, not all children — releases happen at the repo level, so a repo's PRs
  are that repo's concern. This makes the pass **repo-round-robin**: the parent
  rotates its `repos:` the way the orchestrator rotates roster entries. Each pass =
  (1) a GLOBAL step — drain the shared Telegram group and route EVERY message to
  its target repo (record answers on tickets, create fresh tickets in the resolved
  repo) so no repo's messages pile up; then (2) a REPO step for the pass's chosen
  child only — babysit ITS open PRs + build ITS next actionable ticket (subagent in
  that clone). A per-child pre-check (queue_count on the child's project + an
  open-PR check) skips idle children so they don't burn passes, while every
  non-idle child gets its turn (that's how its PRs get babysat with no new ticket).
  This supersedes §10's ticket-priority framing.
- **Q3.** Where does the parent record "which project a question belongs to" for
  reply-routing — the existing questions map already stores `ticket`; add the
  resolved `project`/repo so a reply dispatches to the right clone without a Linear
  round-trip. Proposal: extend the questions entry with `project`.
- **Q4.** Scout scoping: the parent runs the scout per child project (N scans) or
  once team-wide then partitions? Proposal: per project, so proposals carry a repo.

## 16. Codex review (2026-07-13): RETHINK — the false foundations

Codex read this spec against the code and found the "just reuse the machinery"
premise rests on assumptions that are FALSE today. Fixes required before this is
buildable:

1. **The parent is NOT a normal work tree. Introduce an explicit "manager mode."**
   `check_work_tree()` (orch.py:160) rejects `work_tree == root` and demands
   `.dw-agent-clone`; even relaxed, `run-pass.sh:61` and `cron-run.sh:142` `git
   reset --hard` the pass's work tree EVERY pass. §6/§10's "parent never reset" is
   false. A parent entry needs a runner mode that skips the auto-reset and does not
   treat the parent checkout as disposable. (`reset --hard` won't delete gitignored
   child clones / `.agent-loop`, but it wipes tracked parent edits.)
2. **Cross-worktree subagent dispatch is UNPROVEN, not "already reused."** The loop
   does implement via subagents (SKILL.md:20,476) but assumes ONE repo root
   (SKILL.md:27,132); the runner cd's into one `DW_WORK_TREE` and exposes no
   subagent-cwd seam (cron-run.sh:122,199). Whether a headless parent `claude -p`
   can spawn a subagent that operates in a DIFFERENT child clone (own cwd/env/state)
   is the load-bearing unknown. **Prototype it FIRST (below).**
3. **Selector needs real work.** Nothing reads `agent.skill`; validate.py checks
   only `agent.enabled`; **`repos:` fails validation (not in `ALLOWED_TOP`)**; and
   the runner's `DW_SKILL_INVOCATION` wants an invoke STRING (`/dev-workflow:ticket-loop-parent`),
   not a bare skill name. Fix the value shape + add `repos:`/`agent.skill` to the
   schema.
4. **State is one dir per entry.** The orchestrator injects one `STATE_DIR` and
   classifies only from its `outcome.json`/`state.json`/logs + one `loop.lock`
   (orchestrator.sh:282,306; orch.py:449). Child `.agent-loop` is invisible; the
   parent must copy the build's result signal back into the parent state dir. The
   "child loop.lock" idea in §7 is unimplemented.
5. **The Telegram bridge can't carry repo identity.** The questions map is
   `{ticket,text,asked_at}` only (telegram.py:161,212,463); outbound state records
   only with `--ticket`. §5/Q3's pre-ticket "which project?" has NO durable routing
   key. **Bridge change required**: extend the questions entry with `project`/repo,
   and allow recording a pending disambiguation before a ticket exists.
6. **Env bleed.** One `TICKET_LOOP_STATE_DIR` is exported and telegram.py prefers
   it over repo-local (telegram.py:69); a child helper inherits PARENT state unless
   the parent SCRUBS env on child dispatch. The child primitive must rebind
   cwd/env/state explicitly.

**Reordered plan.** Phase 2 (the parent skill) cannot precede proving the
runner/guard/state/bridge contract. New order:
- **Phase 0 (prototype — GO/NO-GO).** A parent `claude -p` pass spawns ONE
  foreground subagent against a different child clone, the subagent reads the
  child's `dev-workflow.yml`, does a trivial change, returns a result, and writes
  NOTHING into the parent's `TICKET_LOOP_STATE_DIR`. If this fails, the design is
  dead — fall back to per-repo-groups (config-only).
- **Phase 1.** Manager mode (no auto-reset for parent entries) + selector
  (`agent.skill` → invoke string) + `repos:` schema + validation. Tests.
- **Phase 2.** The `ticket-loop-parent` skill (only after Phase 0 GO).
- **Phase 3.** Bridge changes (questions map carries project/repo; pre-ticket
  disambiguation key). Required for §5, not optional cleanup.

**Verdict: RETHINK.** The single most important change is manager mode + an
explicit child-execution primitive with cwd/env/state rebinding. Prove Phase 0
before writing any parent-skill code.

## 17. Phase 0 result (2026-07-13): GO

Ran the GO/NO-GO prototype locally. Layout faithful to §4 (child clone as a
subfolder of the parent; parent has a `.agent-loop/state.json` sentinel). A parent
`claude -p ... --dangerously-skip-permissions --model claude-opus-4-8` pass was
told to DELEGATE (not do the work) via a subagent operating entirely in `./child`.

Independently verified (not the model's self-report):
- **Subagent read the child's config + worked in the child dir** — wrote
  `child/RESULT.txt` = `PROTOTYPE BUILD OK: pytest pt_api/` (the child's real
  `quality.test`).
- **Subagent did git ops in the child repo** — branch `proto-1`, new commit on top
  of the child's own history.
- **Parent state untouched** — `parent/.agent-loop/state.json` byte-identical
  (sha matched the pre-run sentinel); no stray files created under it.
- **No parent-checkout mutation** — the work landed only in the child.

Conclusion: cross-worktree subagent dispatch from a headless parent pass, with
isolated parent state, WORKS. The design is not dead. Remaining §16 items
(manager mode / no auto-reset, `agent.skill` selector value shape, `repos:`
schema, result signal-back into the orchestrator STATE_DIR, Telegram bridge repo
identity, env scrub on dispatch) are tractable engineering. Proceed to Phase 1.

NOT tested here (known, deferred to Phase 1 — they are engineering, not unknowns):
run-pass.sh's auto-`reset --hard` of the parent work tree (the manager-mode fix),
the selector plumbing, and signalling the build outcome back to the orchestrator.
