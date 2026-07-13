# GEMINI.md Generator — Gemini CLI

> **Use case:** Projects where developers use [Gemini CLI](https://github.com/google-gemini/gemini-cli) as a terminal-based AI agent.
> For Antigravity (Google's cloud IDE), see [`antigravity-rules-generator.md`](./antigravity-rules-generator.md) — it uses a different rules system.

## What is GEMINI.md

GEMINI.md is the context file for Gemini CLI — Google's terminal-based AI coding agent. Like Claude Code's CLAUDE.md, it provides project-specific instructions, commands, and conventions so the agent understands your codebase without repeating yourself every prompt.

### GEMINI.md Hierarchy

Gemini CLI loads context from multiple levels (all concatenated):

| Level | Location | Scope |
|---|---|---|
| **Global** | `~/.gemini/GEMINI.md` | All projects (your personal defaults) |
| **Project** | `GEMINI.md` in project root | This project's conventions |
| **Subdirectory** | `GEMINI.md` in subdirs | Package-specific rules (monorepos) |
| **Tool-discovered** | Auto-loaded when agent accesses a directory | On-demand context |

### Unique Features

- **Imports:** Break large files into modules with `@./path/to/rules.md` syntax
- **Memory commands:** `/memory show`, `/memory refresh`, `/memory add <text>`
- **Custom filenames:** Configure `settings.json` to also read `AGENTS.md` or `CONTEXT.md`:
  ```json
  { "context": { "fileName": ["GEMINI.md", "AGENTS.md"] } }
  ```
- **`.geminiignore`:** Exclude directories from subdirectory scanning (same syntax as `.gitignore`)

## How to Use

1. Open your terminal in the project root
2. Start Gemini CLI (`gemini`)
3. Paste the prompt below
4. Review the generated GEMINI.md — verify commands, architecture, and conventions
5. **Security check:** confirm `.env`, credentials, and destructive command warnings are in "Protected Areas"
6. **Test the commands:** run each command listed in the "Commands" section
7. Commit to git and push

### Tips

- The **Commands section is the most important** — Gemini CLI will actually execute these
- Use `@imports` to split large GEMINI.md into focused modules (e.g., `@./docs/conventions.md`)
- Create subdirectory GEMINI.md files for monorepo packages
- Use `/memory add` to save quick notes during a session — they go to your global file
- **Global file conflict:** Antigravity also writes to `~/.gemini/GEMINI.md` — if you use both tools, keep project rules in project-level files only
- If something is marked "Unknown" — good, it didn't guess. Fill it in manually.
- **Claude Code users:** the equivalent file is `CLAUDE.md` — see [`claude-md-generator.md`](./claude-md-generator.md)

## The Prompt

Paste this into Gemini CLI and run it against your project.

---

```
Scan this entire project and generate a GEMINI.md file in the project root.

HARD RULE: Base everything on actual repository contents. If something can't be
determined from files present, write "Unknown" — do not guess. If multiple stacks
exist (monorepo), create separate sections per workspace/package/app.

Output ONLY the GEMINI.md file content in Markdown. No preface, no explanation.

========================
CONTEXT
========================
GEMINI.md is read by Gemini CLI — a terminal-based AI agent that can read files,
write code, and execute shell commands. Unlike IDE plugins, Gemini CLI operates
in your full development environment. Write this file as onboarding documentation
for an AI teammate with terminal access.

For large projects, GEMINI.md supports imports: @./path/to/file.md
If the project is complex enough (monorepo, 5+ major directories), split the
output into a main GEMINI.md that imports focused sub-files. Otherwise, keep it
as a single file.

========================
HOW TO SCAN
========================
- Read the actual folder tree and representative files to infer conventions.
- Use sources of truth for stack & versions:
  - JS/TS: package.json, tsconfig.json, eslint/prettier configs, lockfiles
  - Python: pyproject.toml, requirements.txt, setup.cfg, ruff/black configs
  - Ruby: Gemfile, rubocop config
  - Go: go.mod  |  Java/Kotlin: build.gradle / pom.xml  |  .NET: *.csproj
- Check for Dockerfile, docker-compose.yml, Makefile, Justfile, scripts/ —
  these reveal how the project is actually run and built.
- Do NOT assume versions from memory; only use what is declared in the repo.
- If a major framework is detected (e.g., Next.js 14 App Router, Django REST,
  Rails 7, Flutter, Angular), note it explicitly.
- If Google Cloud / Firebase services are detected (Firestore, Cloud Functions,
  Cloud Run, Firebase Auth, etc.), note them explicitly — Gemini has deep
  awareness of Google's ecosystem.

========================
SECTIONS TO INCLUDE
========================

1) Project Overview
   - What this project does, in 1-2 lines. Who is the end user.
   - High-level architecture (e.g., "Next.js frontend + Cloud Functions API + Firestore")

2) Dev Environment Setup
   - Prerequisites: runtime versions, system dependencies
   - Install steps (e.g., `npm install`, `pip install -r requirements.txt`)
   - Required environment variables — list NAMES only, NEVER include values or secrets
   - How to start the dev server / run the application locally
   - Database / emulator setup if applicable

3) Commands
   THIS IS THE MOST IMPORTANT SECTION. Gemini CLI will actually run these commands.
   List the exact, copy-pasteable commands for:
   - Build: e.g., `npm run build`
   - Dev server: e.g., `npm run dev`
   - Test (all): e.g., `npm test`
   - Test (single file): e.g., `npm test -- path/to/file.test.ts`
   - Lint: e.g., `npm run lint`
   - Lint (fix): e.g., `npm run lint -- --fix`
   - Format: e.g., `npm run format`
   - Type check: e.g., `npx tsc --noEmit`
   - Database migrations / emulator: e.g., `firebase emulators:start`
   - Deploy (if applicable): e.g., `firebase deploy --only functions`
   - Any other useful commands from package.json scripts, Makefile, or similar

4) Architecture
   - Key directories and their purpose
   - Core entrypoints: main server file, app root, CLI entry
   - Data flow: how a request moves through the system
   - External dependencies: databases, caches, queues, third-party APIs
   - If multi-service: which service talks to what, API boundaries
   - Point to 1-2 canonical example files that represent "how we write code here"

5) Coding Conventions (inferred from existing code — don't impose new ones)
   - Naming: variables, functions, files, classes
   - Import ordering and export style
   - Type strictness level
   - Error handling pattern: match what exists
   - Testing: framework, naming, file placement, what to mock

6) Common Workflows
   Step-by-step guides for frequent development tasks (infer from project structure):
   - "To add a new API endpoint:" → files to create/modify in order
   - "To add a new component:" → where to create, export, test
   - "To add a new DB model/collection:" → schema/model updates, migration steps
   Include only workflows that can be clearly inferred.

7) Debugging
   - Where logs go (stdout, Cloud Logging, log files)
   - How to run in debug mode
   - Common issues and their fixes (infer from README, CONTRIBUTING, or code comments)

8) Protected Areas — DO NOT TOUCH
   - NEVER read, reference, copy, log, or modify:
     .env, .env.*, config/secrets.*, *.pem, *.key — any secret/key material
   - NEVER run destructive commands without explicit instruction:
     DROP, DELETE FROM, rm -rf, git push --force, git reset --hard,
     firebase projects:delete, gcloud projects delete
   - Do not refactor auth/authentication modules without explicit instruction
   - Never modify existing DB migrations; only create new ones if instructed
   - Never modify CI/CD configs unless explicitly instructed
   - Never edit lockfiles unless the task explicitly requires dependency changes
   - Treat generated/vendor/third-party code as read-only:
     dist/, build/, coverage/, vendor/, node_modules/, __pycache__/, .venv/

========================
MONOREPO: IMPORT STRUCTURE
========================
If this is a monorepo or has 5+ major directories, output a main GEMINI.md that
imports sub-files:

  # Project Name
  ## Overview
  ...
  ## Commands
  ...
  @./docs/gemini/frontend.md
  @./docs/gemini/backend.md
  @./docs/gemini/conventions.md

Then output each imported file separately, clearly labeled.
For simpler projects, keep everything in a single GEMINI.md.

========================
FORMAT
========================
- Plain Markdown with clear headings and short bullets (no YAML frontmatter)
- ALL commands must be in fenced code blocks
- Keep it under ~300 lines for single-file output
- For import-based structure: main file ~100 lines, each import ~50-80 lines
```
