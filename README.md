# ai-dev-prompts

Curated AI prompts for developer workflows — context file generation, codebase documentation, audits, web optimization, and more. Built for teams standardizing on AI-assisted development.

> **⭐ Featured: [`skills/ticket-loop/`](skills/ticket-loop/)** — an autonomous coding agent you manage from a Telegram group. It works your Linear board, asks clarifying questions in the group, and opens one reviewable PR per ticket — no framework, no service to host, just a Claude Code skill + a stdlib-Python bridge. Drop the folder into `.claude/skills/` and follow its README. Full story: [An engineer you manage from a group chat](https://niptao.com/blog/an-engineer-you-manage-from-a-group-chat/).

## The Problem

Every major AI coding tool has its own project context file. Same purpose, different locations:

| Tool | File | Location |
|---|---|---|
| Cursor (legacy) | `.cursorrules` | Project root |
| Cursor (new) | `.cursor/rules/*.mdc` | `.cursor/rules/` directory |
| Claude Code CLI | `CLAUDE.md` | Project root |
| Gemini CLI | `GEMINI.md` | Project root |
| Google Antigravity | `.agent/rules/*.md` | `.agent/rules/` directory |
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/` directory |
| Windsurf | `.windsurfrules` | Project root |
| Cline | `.clinerules` | Project root |
| OpenAI Codex | `AGENTS.md` | Project root |
| Zed | `.zed/settings.json` | `.zed/` directory |

**The content is ~90% the same across all tools.** The investment in one context file is reusable — copy content, change file name.

**Only ~30% of developers use context files.** This is the single biggest gap between "fancy autocomplete" and genuinely productive AI-assisted development.

## What's in This Repo

```
ai-dev-prompts/
├── context-files/           # AI tool context file generators
├── codebase-audit-docs/     # 3-prompt multi-repo audit pipeline
├── web-optimization/        # PageSpeed + SEO/GEO/AEO prompts
├── workflows/               # Process & handover prompts
├── skills/                  # Claude Code skills — full working agents, not just prompts
├── dev-process/             # Full AI-team dev process: branches, worktrees, skills, agent loop
└── site/                    # HTML guide page + assets
```

### 0. Skills (`skills/`) — working Claude Code agents

Complete, drop-in Claude Code skills (a `SKILL.md` plus any helper script it
needs). First entry: [`skills/ticket-loop/`](skills/ticket-loop/) — an
autonomous coding agent that works your Linear board and is managed entirely
from a Telegram group (bug reports with screenshots, approvals, clarifying
questions), opening one reviewable PR per ticket — then babysitting it:
addressing review comments and red CI, healing merge conflicts, closing the
ticket when the PR merges, and reporting in with a daily digest. No framework —
one skill file + one stdlib-Python Telegram bridge; copy the folder into
`.claude/skills/` and follow its README. More skills coming.

### 1. Context File Generators (`context-files/`)

Prompts that scan your existing codebase and auto-generate the right context file for your AI tool. No manual writing required — paste the prompt, review the output, commit.

| Prompt | Tool | Type |
|---|---|---|
| [cursorrules-small-repo.md](context-files/cursorrules-small-repo.md) | Cursor | Single `.cursorrules` file for standard repos |
| [cursorrules-large-repo.md](context-files/cursorrules-large-repo.md) | Cursor | Modular `.cursor/rules/*.mdc` for complex/monorepos |
| [claude-md-generator.md](context-files/claude-md-generator.md) | Claude Code CLI | `CLAUDE.md` — terminal agent onboarding docs |
| [gemini-rules-generator.md](context-files/gemini-rules-generator.md) | Gemini CLI | `GEMINI.md` — terminal agent onboarding docs |
| [antigravity-rules-generator.md](context-files/antigravity-rules-generator.md) | Google Antigravity | `.agent/rules/*.md` with activation modes |

### 2. Codebase Audit & Documentation (`codebase-audit-docs/`)

A 3-prompt pipeline for multi-repo projects. Generates full platform documentation, runs a comprehensive codebase audit, and then updates AI context files in every repo — all using AI. See example output: [Sample Audit Report](https://www.shashanksingla.com/audit-report.html) · [Sample Documentation](https://www.shashanksingla.com/sample-documentation.html).

**The workflow:**

```
1. Documentation  →  2. Audit  →  3. Context Update
   (generates)        (analyzes)     (propagates)
```

| Step | Prompt | What It Does |
|------|--------|-------------|
| 1 | [prompt-documentation.md](codebase-audit-docs/prompt-documentation.md) | Scans all repos, generates platform docs (architecture, API reference, schema, runbook) into a dedicated documentation repo |
| 2 | [prompt-audit.md](codebase-audit-docs/prompt-audit.md) | Reads generated docs + source code, produces a scored audit with executive summary and per-area reports |
| 3 | [prompt-context-update.md](codebase-audit-docs/prompt-context-update.md) | Uses docs + audit findings to update `.cursorrules` and `CLAUDE.md` in every repo |

**Prerequisites:** Install [`gh` CLI](https://cli.github.com/), clone all project repos into one folder, create an empty documentation repo. Full setup instructions in the [codebase-audit-docs README](codebase-audit-docs/README.md).

### 3. Web Optimization (`web-optimization/`)

Prompts for auditing and improving web performance and search visibility. Both follow a 2-phase pattern: audit first, then implement fixes one at a time.

| Prompt | What It Does |
|--------|-------------|
| [pagespeed-optimization.md](web-optimization/pagespeed-optimization.md) | PageSpeed audit — critical request chains, unused JS, render-blocking resources, LCP, image optimization |
| [seo-geo-aeo-optimization.md](web-optimization/seo-geo-aeo-optimization.md) | Full SEO + GEO (AI search engines) + AEO (voice/snippets) audit — meta tags, structured data, llms.txt, FAQ schema |

### 4. Workflows (`workflows/`)

Process prompts for team operations and project management.

| Prompt | What It Does |
|--------|-------------|
| [project-handover.md](workflows/project-handover.md) | Structured handover checklist — credentials, access transfer, infrastructure, DNS, verification steps |

### 5. Dev Process (`dev-process/`)

A complete, battle-tested development process for a small team (or solo founder)
working with AI coding agents — the [full playbook](dev-process/README.md) plus
ready-to-copy scripts and skill templates:

| Piece | What It Does |
|-------|-------------|
| [README.md](dev-process/README.md) | The playbook: two-branch model (`dev` trunk / `main` = prod mirror, deploys only via a deliberate `dev→main` PR), GitHub setup (branch ruleset + auto-delete head branches, with ready `gh api` commands), worktree slots for parallel agent sessions, the daily loop |
| [scripts/worktree-reset.sh](dev-process/scripts/worktree-reset.sh) | Fresh auto-numbered branch off latest `dev` per worktree slot; symlinks shared per-machine state; garbage-collects dead worktrees + merged branches (`--gc`) |
| [scripts/ship-preflight.sh](dev-process/scripts/ship-preflight.sh) | The deterministic git dance behind "wrap up and open a PR" — assess + sync-push in two reviewable calls |
| [skills/standup.md](dev-process/skills/standup.md) | Session opener — board orientation, hygiene line, 2-4 recommended starting points |
| [skills/cleanup.md](dev-process/skills/cleanup.md) | Session closer — commit, push, PR into `dev`, close tickets, handoff notes |
| [skills/release.md](dev-process/skills/release.md) | The `dev→main` promotion that deploys — version bump, tag, release PR; merging stays the human's click |
| [`skills/ticket-loop/`](skills/ticket-loop/) | The autonomous "AI employee" — the drop-in ticket-loop skill (§0) is the agent half of this process: labeled ticket queue, batched questions in team chat, isolated-worktree builds, PR babysitting, daily digest, prompt-injection guardrails |

### Coming Soon

- **Copilot instructions generator** — `.github/copilot-instructions.md`
- **Windsurf / Cline generators** — `.windsurfrules`, `.clinerules`
- **Codex agent generator** — `AGENTS.md`
- **Output templates** — starter templates for each context file format

## Quick Start

### For context file generation (single repo)

1. Pick the prompt that matches your AI tool (see decision tree below)
2. Copy the prompt and paste it into your AI tool
3. **Use the best model available** — Claude Sonnet/Opus, GPT-4o, or Gemini 2.5 Pro
4. Review the output — verify stack versions, conventions, and security rules
5. Commit the generated file to git

### For documentation + audit (multi-repo)

1. Follow the setup in the [codebase-audit-docs README](codebase-audit-docs/README.md)
2. Run the 3 prompts in order: documentation → audit → context update
3. Review, commit, and push all generated files

## Which Prompt Should I Use?

```
What do you need?

Generate a context file for ONE repo
├── IDE (Cursor, Antigravity, VS Code)
│   ├── Simple/single repo? → cursorrules-small-repo.md
│   ├── Complex/monorepo?   → cursorrules-large-repo.md
│   └── Antigravity?        → antigravity-rules-generator.md
└── Terminal agent (CLI)
    ├── Claude Code?  → claude-md-generator.md
    └── Gemini CLI?   → gemini-rules-generator.md

Document & audit a MULTI-REPO platform
└── codebase-audit-docs/ (run all 3 prompts in order)

Optimize web performance
├── PageSpeed / Core Web Vitals → web-optimization/pagespeed-optimization.md
└── SEO / AI search / snippets  → web-optimization/seo-geo-aeo-optimization.md

Hand over a project to a new team
└── workflows/project-handover.md

Set up an AI-assisted dev process for a team
├── Branch model + worktrees + GitHub setup → dev-process/README.md
├── Session skills (standup/cleanup/release) → dev-process/skills/
└── Autonomous ticket-working agent          → skills/ticket-loop/
```

## Design Principles

These prompts are designed to:

1. **Auto-generate from existing code** — scan the repo, don't start from scratch
2. **Never guess** — if something can't be determined, write "Unknown" instead of hallucinating
3. **Enforce security defaults** — credential exclusion, protected areas, destructive command warnings
4. **Be copy-paste ready** — no customization needed for basic setup
5. **Work across stacks** — JS/TS, Python, Ruby, Go, Java, .NET, and more

## Contributing

This repo is a living collection. Contributions are welcome and encouraged.

### Ways to Contribute

- **Improve existing prompts** — found a section that could be clearer, or a case the prompt misses? Open a PR.
- **Add new tool generators** — Windsurf, Cline, Codex, Copilot, Zed — all need prompts.
- **Add workflow prompts** — code review, migration planning, refactoring, debugging workflows.
- **Share your generated output** — if you ran a prompt and the result was great (or terrible), share it as an example so others can learn.
- **Report issues** — if a prompt hallucinates versions, misses conventions, or generates weak security rules, open an issue.

### How to Contribute

1. Fork this repo
2. Create a branch (`git checkout -b add-windsurf-generator`)
3. Add or edit your prompt file
4. Open a PR with a brief description of what changed and why

### What Makes a Good Prompt

- **Grounded in repo contents** — never asks the AI to guess or assume
- **Security-first** — always includes protected areas for secrets, auth, CI/CD
- **Tool-aware** — accounts for what the specific tool can and can't do
- **Concise output** — the generated context file should be useful, not exhaustive

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
