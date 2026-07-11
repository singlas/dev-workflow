# CLAUDE.md

## Project Overview

A curated collection of AI prompts for developer workflows — context file generation, codebase audits, documentation, web optimization, SEO, and project handover. Built for teams standardizing on AI-assisted development.

## Repository Structure

```
ai-dev-prompts/
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
├── skills/                  # Complete drop-in Claude Code skills (not just prompts)
│   └── ticket-loop/         # autonomous coding agent managed from a Telegram group
├── dev-workflow/            # The framework: per-repo config contract + validator + tracker seam
│   ├── README.md            # 3 zones, 2 boundary rules, distribution
│   ├── dev-workflow.example.yml  # annotated full config (generic values)
│   ├── validate.py          # schema + tighten-only validator (PyYAML)
│   ├── dw-config.py          # dotted-path config reader for shell callers
│   ├── test_validate.py     # unittest for validate.py
│   └── tracker-adapters.md  # canonical verbs → provider mapping (Linear impl)
├── dev-process/             # AI-team dev process: playbook + scripts + skill templates
│   ├── README.md            # branch model, worktrees, GitHub setup, daily loop, agent loop
│   ├── scripts/             # worktree-reset.sh, ship-preflight.sh (ready to copy)
│   └── skills/              # standup, cleanup, release templates (agent loop → ../skills/)
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

- All prompts are Markdown files organized into categorized subdirectories
- README.md serves as the main index with a decision tree for prompt selection
- Each prompt category has its own folder and numbered section in the README
- `site/` contains the HTML guide page and is not a prompt directory
- `dev-workflow/` is a real framework, not prompts: the per-repo `dev-workflow.yml`
  contract, its PyYAML validator (`validate.py` — enforces boundary rule 1,
  config can only tighten, never loosen), the dotted-path reader (`dw-config.py`),
  and the tracker-adapter seam. Keep names in sync with the ticket-loop runner
  (`skills/ticket-loop/`) and the `.claude-plugin/plugin.json` (plugin name
  `dev-workflow`). New Python here must pass `python3 -m py_compile`; the
  validator has a `test_validate.py` (`python3 dev-workflow/test_validate.py`)
