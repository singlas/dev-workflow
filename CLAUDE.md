# CLAUDE.md

## Project Overview

`dev-workflow` is the framework — **CI, but for ticket work.** A generic runner +
Claude Code plugin read one per-repo `dev-workflow.yml` and work your board
(pick up tickets, ask questions in team chat, open one reviewable PR each)
inside guardrails a repo can tighten but never loosen. The framework leads;
the original standalone AI-prompt collections (context files, audits,
web-optimization, handover) still ship here as a secondary section.

## Repository Structure

```
dev-workflow/
├── dev-workflow/            # THE FRAMEWORK: per-repo config contract + validator + tracker seam
│   ├── README.md            # 3 zones, 2 boundary rules, baseline guardrails, distribution
│   ├── dev-workflow.example.yml  # annotated full config (generic values)
│   ├── validate.py          # schema + tighten-only validator (PyYAML)
│   ├── dw-config.py          # dotted-path config reader for shell callers
│   ├── test_validate.py     # unittest for validate.py
│   └── tracker-adapters.md  # canonical verbs → provider mapping (Linear impl)
├── skills/                  # Claude Code plugin skills — standup, cleanup, release, ticket-loop
│   ├── standup/  cleanup/  release/   # session skills, driven by dev-workflow.yml
│   └── ticket-loop/         # autonomous agent + docker/ runner packaging
├── dev-process/             # The narrative playbook behind the skills
│   ├── README.md            # branch model, worktrees, GitHub setup, daily loop, agent loop
│   └── scripts/             # worktree-reset.sh, ship-preflight.sh (ready to copy)
├── .claude-plugin/          # Plugin manifest (plugin name: dev-workflow)
│   └── plugin.json
│   # ── legacy prompt collections (secondary in the README) ──
├── context-files/           # Prompts that generate AI tool context files
│   ├── cursorrules-small-repo.md
│   ├── cursorrules-large-repo.md
│   ├── claude-md-generator.md
│   ├── gemini-rules-generator.md
│   └── antigravity-rules-generator.md
├── codebase-audit-docs/     # 3-prompt pipeline for multi-repo documentation + audit
│   ├── prompt-documentation.md
│   ├── prompt-audit.md
│   └── prompt-context-update.md
├── web-optimization/        # Web performance + SEO prompts
│   ├── pagespeed-optimization.md
│   └── seo-geo-aeo-optimization.md
├── workflows/               # Process & handover prompts
│   └── project-handover.md
├── site/                    # HTML guide page + static assets
│   ├── index.html
│   └── assets/
└── README.md
```

## Content Guidelines

- Prompts should be copy-paste ready — no customization needed for basic use
- Use `[PLACEHOLDER]` syntax for values the user must fill in
- Never ask AI to guess — instruct it to write "Unknown" if something can't be determined
- Include security defaults (credential exclusion, protected areas)
- Structure prompts as Phase 1 (Audit) → Phase 2 (Implement) where applicable
- One commit per fix pattern for implementation prompts

## Conventions

- README.md leads with the framework (pitch → quickstart → how it's put together)
  and demotes the prompt collections into a secondary "Also in this repo" section;
  keep that ordering when editing
- All prompts are Markdown files organized into categorized subdirectories
- Each prompt collection has its own folder and a numbered subsection in the README
- `site/` contains the HTML guide page and is not a prompt directory
- `dev-workflow/` is a real framework, not prompts: the per-repo `dev-workflow.yml`
  contract, its PyYAML validator (`validate.py` — enforces boundary rule 1,
  config can only tighten, never loosen), the dotted-path reader (`dw-config.py`),
  and the tracker-adapter seam. Keep names in sync with the ticket-loop runner
  (`skills/ticket-loop/`) and the `.claude-plugin/plugin.json` (plugin name
  `dev-workflow`). New Python here must pass `python3 -m py_compile`; the
  validator has a `test_validate.py` (`python3 dev-workflow/test_validate.py`)
