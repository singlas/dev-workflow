# CLAUDE.md Generator — Claude Code CLI

> **Use case:** Projects where developers use [Claude Code](https://docs.anthropic.com/en/docs/claude-code) as a terminal-based AI agent.
> CLAUDE.md is not needed when using Claude inside Cursor — that's what `.cursorrules` is for.

## What Makes CLAUDE.md Different

CLAUDE.md is **not** editor behavior rules. Claude Code is a terminal agent — it reads files, writes code, runs shell commands, creates commits, and navigates your entire filesystem. Think of CLAUDE.md as **onboarding documentation for an AI teammate with terminal access**.

| `.cursorrules` (Cursor) | `CLAUDE.md` (Claude Code CLI) |
|---|---|
| Editor behavior rules | Operational onboarding docs |
| "Remind user to run tests" | `npm test -- --watch` (runs it directly) |
| IDE autocomplete context | Full filesystem + shell access |
| Single file, always loaded | Hierarchical (root + subdirs) |

### CLAUDE.md Hierarchy

Claude Code loads CLAUDE.md from multiple levels:
- **Parent directories** — org-wide or shared conventions
- **Project root** — main project context (this is what the prompt generates)
- **Subdirectories** — package-specific rules in monorepos (`packages/api/CLAUDE.md`)

## How to Use

1. Open your terminal in the project root
2. Start Claude Code (`claude`)
3. Paste the prompt below
4. Review the generated CLAUDE.md — verify commands, architecture, and conventions
5. **Security check:** confirm `.env`, credentials, keys, and destructive command warnings are in "Protected Areas"
6. **Test the commands:** run each command listed in the "Commands" section to make sure they're correct
7. Commit to git and push

### Tips

- The **Commands section is the most important** — Claude Code will actually execute these. Get them right.
- Create subdirectory CLAUDE.md files for monorepo packages (`packages/api/CLAUDE.md`, `packages/web/CLAUDE.md`)
- Update CLAUDE.md when you add new libraries, change build tools, or alter project structure
- Add rules when Claude Code makes a recurring mistake — e.g., "always use `pnpm` not `npm`"
- If something is marked "Unknown" — good, it means it didn't guess. Fill it in manually.
- **Cursor users:** the equivalent file is `.cursorrules` — see [`cursorrules-small-repo.md`](./cursorrules-small-repo.md)

## The Prompt

Paste this into Claude Code and run it against your project.

---

```
Scan this entire project and generate a CLAUDE.md file in the project root.

HARD RULE: Base everything on actual repository contents. If something can't be
determined from files present, write "Unknown" — do not guess. If multiple stacks
exist (monorepo), create separate sections per workspace/package/app.

Output ONLY the CLAUDE.md file content in Markdown. No preface, no explanation.

========================
CONTEXT
========================
CLAUDE.md is read by Claude Code — a terminal-based AI agent that can read files,
write code, and execute shell commands. Unlike IDE plugins, Claude Code operates
in your full development environment. Write this file as onboarding documentation
for an AI teammate with terminal access, not as editor behavior rules.

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
  Rails 7), note it explicitly so Claude prioritizes that framework's idioms.

========================
SECTIONS TO INCLUDE
========================

1) Project Overview
   - What this project does, in 1-2 lines. Who is the end user.
   - High-level architecture (e.g., "Next.js frontend + Express API + PostgreSQL")

2) Dev Environment Setup
   - Prerequisites: runtime versions, system dependencies (e.g., Node 20, Python 3.12, Docker)
   - Install steps (e.g., `npm install`, `pip install -r requirements.txt`)
   - Required environment variables — list NAMES only, NEVER include values or secrets
   - How to start the dev server / run the application locally
   - Database setup if applicable (e.g., `docker compose up db`, migration command)

3) Commands
   THIS IS THE MOST IMPORTANT SECTION. Claude Code will actually run these commands.
   List the exact, copy-pasteable commands for:
   - Build: e.g., `npm run build`
   - Dev server: e.g., `npm run dev`
   - Test (all): e.g., `npm test`
   - Test (single file): e.g., `npm test -- path/to/file.test.ts`
   - Lint: e.g., `npm run lint`
   - Lint (fix): e.g., `npm run lint -- --fix`
   - Format: e.g., `npm run format`
   - Type check: e.g., `npx tsc --noEmit`
   - Database migrations: e.g., `npx prisma migrate dev`
   - Any other useful commands from package.json scripts, Makefile, Justfile, or similar
   If the project uses a task runner (make, just, nx, turbo), document its commands.

4) Architecture
   - Key directories and their purpose
   - Core entrypoints: main server file, app root, CLI entry, worker entry
   - Data flow: how a request moves through the system (e.g., "route → controller → service → repository → DB")
   - External dependencies: databases, caches, queues, third-party APIs, internal services
   - If multi-service: which service talks to what, API boundaries, shared types/contracts
   - Point to 1-2 canonical example files that represent "how we write code here"

5) Coding Conventions (inferred from existing code — don't impose new ones)
   - Naming: variables, functions, files, classes (camelCase/snake_case/PascalCase/kebab-case)
   - Import ordering and export style (named vs default)
   - Type strictness: strict types, `any`, or no types?
   - Error handling pattern: early returns, try/catch, custom error classes — match what exists
   - Testing: framework, naming, file placement, what to mock vs what to test with real implementations

6) Common Workflows
   Step-by-step guides for frequent development tasks. Infer from existing code:
   - "To add a new API endpoint:" → list the files to create/modify in order
   - "To add a new React component:" → where to create, how to export, where to add tests
   - "To add a new DB model/table:" → migration command, model file, type updates
   - "To add a new CLI command:" → where commands are registered, handler pattern
   Include only workflows that can be clearly inferred from the project structure.

7) Debugging
   - Where logs go (stdout, log files, external logging service)
   - How to run in debug mode (if evident from configs, e.g., `DEBUG=* npm start`)
   - Common issues and their fixes (infer from README, CONTRIBUTING, code comments, or Troubleshooting docs)
   - How to inspect the database (e.g., `npx prisma studio`, `psql` connection string pattern)

8) Protected Areas — DO NOT TOUCH
   - NEVER read, reference, copy, log, or modify:
     .env, .env.*, config/secrets.*, *.pem, *.key — any secret/key material
   - NEVER run destructive commands without explicit instruction:
     DROP, DELETE FROM, rm -rf, git push --force, git reset --hard
   - Do not refactor auth/authentication modules without explicit instruction
   - Never modify existing DB migrations; only create new ones if instructed
   - Never modify CI/CD configs (.github/workflows, Jenkinsfile, docker-compose.prod.yml)
   - Never edit lockfiles unless the task explicitly requires dependency changes
   - Treat generated/vendor/third-party code as read-only:
     dist/, build/, coverage/, vendor/, node_modules/, __pycache__/, .venv/

========================
FORMAT
========================
- Markdown with clear headings and short bullets
- ALL commands must be in fenced code blocks — Claude Code will copy-paste and execute them
- Keep it under ~300 lines — comprehensive but not exhaustive
- Think of this as the document you'd hand a senior developer on their first day
```
