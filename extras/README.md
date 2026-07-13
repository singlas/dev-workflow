# Extras — the standalone prompt collections

Before the framework, this repo was a curated set of copy-paste AI prompts for
developer workflows. They still work exactly as they always did — paste into
your AI tool, no install required — but they're secondary to the
[framework](../README.md) now, so they live here.

## Context file generators (`context-files/`)

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

## Codebase audit & documentation (`codebase-audit-docs/`)

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

## Web optimization (`web-optimization/`)

Prompts for auditing and improving web performance and search visibility — each
follows a 2-phase pattern: audit first, then implement fixes one at a time.

| Prompt | What It Does |
|--------|-------------|
| [pagespeed-optimization.md](web-optimization/pagespeed-optimization.md) | PageSpeed audit — critical request chains, unused JS, render-blocking resources, LCP, image optimization |
| [seo-geo-aeo-optimization.md](web-optimization/seo-geo-aeo-optimization.md) | Full SEO + GEO (AI search engines) + AEO (voice/snippets) audit — meta tags, structured data, llms.txt, FAQ schema |

## Handover (`handover/`)

| Prompt | What It Does |
|--------|-------------|
| [project-handover.md](handover/project-handover.md) | Structured handover checklist — credentials, access transfer, infrastructure, DNS, verification steps |

## Design principles

The prompt collections are designed to:

1. **Auto-generate from existing code** — scan the repo, don't start from scratch
2. **Never guess** — if something can't be determined, write "Unknown" instead of hallucinating
3. **Enforce security defaults** — credential exclusion, protected areas, destructive command warnings
4. **Be copy-paste ready** — no customization needed for basic setup
5. **Work across stacks** — JS/TS, Python, Ruby, Go, Java, .NET, and more

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
