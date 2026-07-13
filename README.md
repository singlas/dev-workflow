# dev-workflow

**CI, but for ticket work.** A generic runner + a Claude Code plugin read one
per-repo `dev-workflow.yml` and work your board — picking up tickets, asking
clarifying questions in team chat, and opening one reviewable PR per ticket —
inside guardrails a repo can *tighten but never loosen*. Same shape as CI:
generic runner, per-repo config file, non-escapable guardrails. Point it at any
codebase.

Three tiers, adopt as far as you want to go:

- **v1 — Local developer (default, every install).** Install the plugin, run
  `/setup` to write a `dev-workflow.yml`, and work locally: `/standup` to orient,
  `/cleanup` to ship a PR, `/release` to promote, `/blog-from-session` on the
  side. Worktree-based branch workflow. This is what you get out of the box.
- **v2 — Local agent (opt-in, OFF by default).** A local autonomous agent (the
  `ticket-loop` skill + a launchd/cron installer) that works your queue on your
  machine and opens one PR per ticket. Gated by `agent.enabled: true` in
  `dev-workflow.yml` — absent/false and both the skill and installer refuse.
- **v3 — Remote runner (repo-level, separate).** The Docker runner + multi-project
  orchestrator — an AI teammate you manage from a Telegram group, running
  unattended on a server. Not part of plugin install; it has its own runbook
  track (§ *Autonomous ticket-loop* below).

**Works today with [Linear](https://linear.app) as the tracker and
[Telegram](https://telegram.org) as the team chat.** Both sit behind an adapter
seam ([tracker-adapters.md](dev-workflow/tracker-adapters.md)) — GitHub Issues /
Jira / Slack later means a new mapping, not a rewrite.

Secrets are injected at runtime; the framework is baked **read-only** so the
agent physically cannot edit its own leash. The narrative behind the skills is
the [dev-process playbook](dev-process/README.md).

> This repo was previously a collection of standalone AI prompts. Those still
> ship here — see **[§4 Also in this repo: the prompt collections](#4-also-in-this-repo-the-prompt-collections)** —
> but the framework is now the front door.

## 1. Quickstart

**You need:** [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with
your tracker connected (Linear's MCP, or a `LINEAR_API_KEY` for the headless
loop). Only for the autonomous loop and release announcements: a Telegram bot
token + group chat id, and a GitHub token for PRs — all injected via env vars,
enumerated in [`skills/ticket-loop/env.example`](skills/ticket-loop/env.example).

### Interactive skills

1. **Install the plugin.** Either `claude plugin install` (plugin name
   `dev-workflow`), or point Claude Code at a clone of this repo:

   ```
   claude --plugin-dir <path-to-this-clone>
   ```

   It provides `/setup`, `/standup`, `/cleanup`, `/release`, `/ticket-loop`, and
   `/blog-from-session`. Opening a session in a repo that already has a
   `dev-workflow.yml` auto-orients you (a SessionStart hook injects a short brief;
   it stays silent in every repo without one).

2. **Add a config.** Run `/setup` — it checks prereqs and interviews you for the
   required values, writing a validated `dev-workflow.yml`. Or copy
   [`dev-workflow.example.yml`](dev-workflow/dev-workflow.example.yml) to your
   repo root by hand and edit the values (branch model, tracker team/roles,
   test/lint commands, tightened guardrails).

3. **Validate it:**

   ```
   uv run dev-workflow/validate.py dev-workflow.yml     # -> OK: dev-workflow.yml
   ```

   The validator rejects unknown keys and any config that tries to *loosen* a
   baseline (see the boundary rules below).

4. **Open a session** with `/standup`, close it with `/cleanup`, promote with
   `/release`.

### The skills at a glance

Each skill reads `dev-workflow.yml` for your branch names, tracker roles, and
commands — and each sits one step further up a deliberate safety gradient:

| Skill | What it does | Blast radius |
|---|---|---|
| `/setup` | First-run onboarding: checks prereqs (git/uv/gh/tracker key), interviews you, writes a validated `dev-workflow.yml`, points at the daily workflow | Writes one local file (`dev-workflow.yml`); never commits or pushes |
| `/standup` | Opens a session: board snapshot, what's In Progress to resume, 2-4 recommended starting tickets with one-line whys | **Read-only** — never moves a ticket |
| `/cleanup` | Closes a session: commit what's left → sync with the base branch → push → open the PR → move the session's finished tickets to Done | Pushes *your feature branch*; merging its PR lands on the base branch and **never deploys** |
| `/release` | The promotion: absorb hotfixes, test gate, bump `version.file`, tag, open the base→prod PR — then **stops. A human merges; the merge deploys.** Refuses to run at all if `repo.prod_branch` / `deploy.trigger` aren't configured | The **only** skill that touches prod, and it's human-gated at the merge |
| `/ticket-loop` | One pass of the autonomous agent (v2): daily digest → drain the Telegram group (answers, new tickets, approvals) → babysit open PRs → build the next actionable tickets, one PR each. Opt-in: refuses interactively unless `agent.enabled: true` | Same baseline guardrails as the containerized runner |
| `/blog-from-session` | Optional: turns a sharp session learning (or a topic you hand it) into one practitioner field-note draft — proposes angles, then writes the pick. Enabled by a `blog:` config section; `/cleanup` can offer it | Writes one draft file locally; never publishes or commits |

### Autonomous ticket-loop (v2 local agent · v3 remote runner)

The same loop runs unattended two ways. **v2** is a local agent you turn on per
repo; **v3** is a separate, repo-level deployment on a server. Both run the
identical runner + skill — the difference is where it lives and how it's gated.

**v2 — Local agent (opt-in).** An autonomous agent on your own machine, scheduled
via macOS launchd (adapt to cron/systemd on Linux). Turn it on in three steps:

1. **Opt in.** Set `agent.enabled: true` in the repo's `dev-workflow.yml` (the
   `/setup` skill can do this). Without it, `/ticket-loop` and the installer both
   refuse.
2. **Supply the loop's env** — Telegram bot token + group chat id, `GH_TOKEN`,
   `LINEAR_API_KEY` — see [`skills/ticket-loop/env.example`](skills/ticket-loop/env.example).
3. **Install the schedule** with
   [`skills/ticket-loop/install-cron.sh`](skills/ticket-loop/install-cron.sh)
   (`--work-tree <your repo>`). What the agent does and how you manage it from a
   group chat: [`skills/ticket-loop/README.md`](skills/ticket-loop/README.md).

**v3 — Remote runner (repo-level, separate — NOT part of plugin install).** The
Docker image + multi-project orchestrator, running on a server against mounted
work trees. It is intentionally *not* gated on `agent.enabled` (a live deployment
predates that key). Follow the docs in order:

1. **Build + run one repo** — build the image, mount a work tree, set the timer:
   [`skills/ticket-loop/docker/README.md`](skills/ticket-loop/docker/README.md).
2. **Scale to many repos** — the round-robin orchestrator (roster, pre-check,
   backoff) over the same image:
   [`skills/ticket-loop/orchestrator/README.md`](skills/ticket-loop/orchestrator/README.md).

## 2. How it's put together

Everything splits into **three zones** — the framework is generic and shared,
the target repo owns only its config, and secrets live nowhere in git. Full
detail (baseline guardrails, tracker seam, distribution) is the deep-dive in
[`dev-workflow/README.md`](dev-workflow/README.md).

| Zone | Owns | Lives in |
|---|---|---|
| **Framework** (generic) | Plugin (skills), runner scripts, Docker image, validator. Identical across every repo. | This repo — `.claude-plugin/` + `skills/` + `dev-workflow/`; baked root-owned at `/opt/dev-workflow` in the container. |
| **Target-repo config** | One `dev-workflow.yml` + the repo's own `CLAUDE.md`. Branch model, tracker team/roles, commands, tightened guardrails. | The target repo root. |
| **Injected** | Secrets (`agent.env`), Claude auth (`~/.claude`), the loop's `state.json`. Never in git. | A mounted volume / the runtime environment. |

Two boundary rules make it safe to point at any repo:

1. **Config can only tighten, never loosen.** Baseline guardrails are
   framework-side constants. A `dev-workflow.yml` may *add* protected paths or
   *lower* a diff budget, but can never switch a baseline off or raise a ceiling.
   `validate.py` enforces the ceilings; the runner enforces the baseline.
2. **The runner lives outside the mounted work tree.** In the container the
   runner + plugin are baked root-owned at `/opt/dev-workflow`; the target repo
   is the mounted volume the build subagent edits as a non-root user — so it
   *physically cannot* edit the framework driving it.

The framework files:

| Piece | What It Does |
|-------|-------------|
| [dev-workflow/README.md](dev-workflow/README.md) | Framework overview: three zones, two boundary rules, baseline guardrails, distribution (Docker runner + Claude Code plugin) |
| [dev-workflow/dev-workflow.example.yml](dev-workflow/dev-workflow.example.yml) | Annotated full config — branch model, tracker team/roles, test/lint commands, tightened guardrails, schedule |
| [dev-workflow/validate.py](dev-workflow/validate.py) | Schema + tighten-only validator — rejects unknown keys and any config that raises a ceiling |
| [dev-workflow/dw-config.py](dev-workflow/dw-config.py) | Dotted-path config reader shell scripts use (`dw-config.py dev-workflow.yml tracker.team`) |
| [dev-workflow/dw-board.py](dev-workflow/dw-board.py) | Framework board tool — `dw-board snapshot` renders the board views from Linear, `dw-board prune` reports (config-gated) old Done/Canceled tickets, `dw-board import` bulk-creates issues from a JSON holding file (dry-run unless `--yes`). Team + gates + prune policy from config; `LINEAR_API_KEY` from the env only |
| [dev-workflow/tracker-adapters.md](dev-workflow/tracker-adapters.md) | The provider seam — canonical verbs (`list_actionable`, `move`, `label`, …) mapped onto a tracker (Linear today; GitHub Issues sketch) |
| [skills/standup/](skills/standup/) · [skills/cleanup/](skills/cleanup/) · [skills/release/](skills/release/) | The session skills — open a session, close it into a PR, promote to prod. Driven entirely by `dev-workflow.yml` |
| [skills/ticket-loop/](skills/ticket-loop/) | The autonomous agent + its [`docker/`](skills/ticket-loop/docker/) runner packaging |

## 3. Repo map

```
dev-workflow/
├── dev-workflow/            # The framework: config contract + validator + tracker seam
├── skills/                  # Claude Code plugin skills — standup, cleanup, release, ticket-loop
├── dev-process/             # The narrative playbook behind the skills (branches, worktrees, loop)
├── .claude-plugin/          # Plugin manifest (plugin name: dev-workflow)
├── context-files/           # (collection) AI tool context-file generators
├── codebase-audit-docs/     # (collection) 3-prompt multi-repo audit pipeline
├── web-optimization/        # (collection) PageSpeed + SEO/GEO/AEO prompts
├── workflows/               # (collection) Process & handover prompts
└── site/                    # HTML guide page + assets
```

## 4. Also in this repo: the prompt collections

Before the framework, this repo was a curated set of standalone AI prompts for
developer workflows. They still ship here — copy-paste into your AI tool, no
install required.

### Context file generators (`context-files/`)

Prompts that scan your existing codebase and auto-generate the right context
file for your AI tool. Every major AI coding tool has its own project context
file — same purpose, different location; the content is ~90% the same across
all of them.

| Prompt | Tool | Type |
|---|---|---|
| [cursorrules-small-repo.md](context-files/cursorrules-small-repo.md) | Cursor | Single `.cursorrules` file for standard repos |
| [cursorrules-large-repo.md](context-files/cursorrules-large-repo.md) | Cursor | Modular `.cursor/rules/*.mdc` for complex/monorepos |
| [claude-md-generator.md](context-files/claude-md-generator.md) | Claude Code CLI | `CLAUDE.md` — terminal agent onboarding docs |
| [gemini-rules-generator.md](context-files/gemini-rules-generator.md) | Gemini CLI | `GEMINI.md` — terminal agent onboarding docs |
| [antigravity-rules-generator.md](context-files/antigravity-rules-generator.md) | Google Antigravity | `.agent/rules/*.md` with activation modes |

### Codebase audit & documentation (`codebase-audit-docs/`)

A 3-prompt pipeline for multi-repo projects: generate full platform docs, run a
scored audit, then update AI context files in every repo. Run them **in order**.
See example output: [Sample Audit Report](https://www.shashanksingla.com/audit-report.html) ·
[Sample Documentation](https://www.shashanksingla.com/sample-documentation.html).

| Step | Prompt | What It Does |
|------|--------|-------------|
| 1 | [prompt-documentation.md](codebase-audit-docs/prompt-documentation.md) | Scans all repos, generates platform docs (architecture, API reference, schema, runbook) into a dedicated documentation repo |
| 2 | [prompt-audit.md](codebase-audit-docs/prompt-audit.md) | Reads generated docs + source code, produces a scored audit with executive summary and per-area reports |
| 3 | [prompt-context-update.md](codebase-audit-docs/prompt-context-update.md) | Uses docs + audit findings to update `.cursorrules` and `CLAUDE.md` in every repo |

Setup (clone all repos, create an empty docs repo): [codebase-audit-docs README](codebase-audit-docs/README.md).

### Web optimization (`web-optimization/`)

Prompts for auditing and improving web performance and search visibility — each
follows a 2-phase pattern: audit first, then implement fixes one at a time.

| Prompt | What It Does |
|--------|-------------|
| [pagespeed-optimization.md](web-optimization/pagespeed-optimization.md) | PageSpeed audit — critical request chains, unused JS, render-blocking resources, LCP, image optimization |
| [seo-geo-aeo-optimization.md](web-optimization/seo-geo-aeo-optimization.md) | Full SEO + GEO (AI search engines) + AEO (voice/snippets) audit — meta tags, structured data, llms.txt, FAQ schema |

### Workflows (`workflows/`)

| Prompt | What It Does |
|--------|-------------|
| [project-handover.md](workflows/project-handover.md) | Structured handover checklist — credentials, access transfer, infrastructure, DNS, verification steps |

### Dev process (`dev-process/`)

The full playbook the framework grew out of — the two-branch model (`dev` trunk
/ `main` = prod mirror), GitHub setup, worktree slots for parallel agent
sessions, and the daily loop — plus ready-to-copy scripts. The plugin skills
(`standup`/`cleanup`/`release`/`ticket-loop`) are the productized form of it.

| Piece | What It Does |
|-------|-------------|
| [README.md](dev-process/README.md) | The narrative playbook: branch model, GitHub ruleset, worktree slots, the daily loop |
| [scripts/worktree-reset.sh](dev-process/scripts/worktree-reset.sh) | Fresh auto-numbered branch off latest `dev` per worktree slot; symlinks shared state; GCs dead worktrees + merged branches |
| [scripts/ship-preflight.sh](dev-process/scripts/ship-preflight.sh) | The deterministic git dance behind "wrap up and open a PR" — assess + sync-push in two reviewable calls |

## 5. Design principles

The prompt collections are designed to:

1. **Auto-generate from existing code** — scan the repo, don't start from scratch
2. **Never guess** — if something can't be determined, write "Unknown" instead of hallucinating
3. **Enforce security defaults** — credential exclusion, protected areas, destructive command warnings
4. **Be copy-paste ready** — no customization needed for basic setup
5. **Work across stacks** — JS/TS, Python, Ruby, Go, Java, .NET, and more

## 6. Contributing

This repo is a living collection. Contributions are welcome.

- **Improve the framework** — sharper guardrails, a new tracker adapter, a
  cleaner runner.
- **Improve existing prompts** — clearer sections, cases a prompt misses.
- **Add new tool generators** — Windsurf, Cline, Codex, Copilot, Zed.
- **Share your generated output** — great (or terrible) results make good
  examples for others.

To contribute: fork, branch (`git checkout -b my-change`), edit, and open a PR
with a brief description of what changed and why.

## References

- [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) — 130+ community .cursorrules examples
- [ai-prompts by instructa](https://github.com/instructa/ai-prompts) — curated prompts for Cursor, Cline, Windsurf, Copilot
- [Cursor rules docs](https://docs.cursor.com/context/rules-for-ai) — official `.cursor/rules/` documentation
- [Gemini CLI docs](https://github.com/google-gemini/gemini-cli) — GEMINI.md and CLI reference
- [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code) — CLAUDE.md and CLI reference
- [Google Antigravity](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/) — Antigravity platform overview

### Useful Claude Code Skills & Agent Roles

Community-built skills and agent configurations you can add to Claude Code:

- [agency-agents](https://github.com/msitarzewski/agency-agents) — specialized agent roles for Claude Code
- [gstack](https://github.com/garrytan/gstack) — skills for QA, design review, shipping, and more
- [get-shit-done](https://github.com/gsd-build/get-shit-done) — productivity-focused agent skills
- [Claude Code Game Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) — 48 specialized agents mirroring a real studio hierarchy (Art Director, Level Designer, QA Lead, Sound Designer, etc.) with 36 workflow skills covering the full game dev lifecycle
- [everything-claude-code](https://github.com/affaan-m/everything-claude-code) — complete performance optimization system from an Anthropic hackathon winner: skills, instincts, memory optimization, continuous learning, security scanning, and research-first development. Works across Claude Code, Codex, Cowork, and other AI agent harnesses

### Tools & Templates

- [ai-website-cloner-template](https://github.com/JCodesMore/ai-website-cloner-template) — AI-powered website cloning template
- [youtube-shorts-pipeline](https://github.com/rushindrasinha/youtube-shorts-pipeline) — one command to research, script, generate b-roll, voiceover, animated captions, background music, thumbnail, and upload to YouTube (~90s video, ~3min wall time, ~$0.11 API cost)
- [the-book-of-secret-knowledge](https://github.com/trimstray/the-book-of-secret-knowledge) — massive collection of CLI tools, one-liners, cheat sheets, web resources, manuals, and more for sysadmins, devops, pentesters, and researchers
- [llmfit](https://github.com/AlexsJones/llmfit) — terminal tool that right-sizes LLM models to your hardware, scoring each model across quality, speed, fit, and context dimensions based on your RAM, CPU, and GPU
- [Qwen3-Coder](https://github.com/QwenLM/Qwen3-Coder) — open-source coding model (3B active params, MoE) with Qwen Code CLI — open-source alternative to Claude Code with 1,000 free requests/day

### Cost Optimization

- [Reducing AI API call costs](https://x.com/ziwenxu_/status/2036277868246749581) — strategies for minimizing API spend

## License

MIT
