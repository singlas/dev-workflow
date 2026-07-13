# .cursorrules Generator — Standard / Single Repos

> **Use case:** Single-repo projects of small to medium complexity.
> For monorepos or large multi-service codebases, see [`cursorrules-large-repo.md`](./cursorrules-large-repo.md).

## How to Use

1. Open your project in Cursor
2. Open Agent mode (Cmd+I / Ctrl+I)
3. Paste the prompt below
4. **Use the best model available** (Claude Sonnet/Opus or GPT-4o) — smaller models skip sections or hallucinate versions
5. Review what it generates — make sure it got the stack, structure, and conventions right
6. **Security check:** confirm `.env`, credentials, keys, and auth modules are in the "Protected Areas" section. Add any project-specific sensitive files that aren't covered.
7. Commit to git and push

### Tips

- Commit `.cursorrules` to git — it's part of the project, not personal config
- Update it when you add new libraries, patterns, or architectural decisions
- Add rules when the AI makes a recurring mistake ("never use X for Y")
- If the AI marked something as "Unknown" — that's good, it means it didn't guess. Fill it in manually.
- **Claude Code CLI users:** the equivalent file is `CLAUDE.md` — same concept, see [`claude-md-generator.md`](./claude-md-generator.md)

## The Prompt

Copy-paste this into Cursor Agent mode and run it against your project.

---

```
Scan this entire project and generate a .cursorrules file in the project root.

HARD RULE: Base everything on actual repository contents. If something can't be determined from files present, write "Unknown" — do not guess. If multiple stacks exist (monorepo), create separate sections per workspace/package/app.

Output ONLY the .cursorrules file content in Markdown. No preface, no explanation.

========================
HOW TO SCAN
========================
- Read the actual folder tree and representative files to infer conventions.
- Use sources of truth for stack & versions:
  - JS/TS: package.json, tsconfig.json, eslint/prettier configs, lockfiles
  - Python: pyproject.toml, requirements.txt, setup.cfg, ruff/black configs
  - Ruby: Gemfile, rubocop config
  - Go: go.mod  |  Java/Kotlin: build.gradle / pom.xml  |  .NET: *.csproj
- Do NOT assume versions from memory; only use what is declared in the repo.
- If a major framework is detected (e.g., Next.js 14 App Router, Django REST, Rails 7), note it explicitly so the AI prioritizes that framework's patterns over generic ones.

========================
SECTIONS TO INCLUDE
========================

1) Project Overview
   - What this project does, in 1-2 lines. Who is the end user.

2) Stack & Versions
   - Languages, frameworks/runtimes, major libraries (with versions from config files)
   - Tooling: lint, format, test runner, build tool

3) Project Structure
   - Key directories and their purpose
   - Where core entrypoints live
   - Point to 1-2 canonical example files (a good component, service, API route, test) so the AI knows what "good" looks like in this repo

4) Coding Conventions (inferred from existing code — don't impose new ones)
   - Naming: variables, functions, files, classes (camelCase/snake_case/PascalCase/kebab-case)
   - Component style: functional vs class, hooks patterns
   - Import ordering and export style (named vs default)
   - Type strictness: does the project use strict types, `any`, or no types?
   - Error handling pattern: early returns, try/catch, custom error classes — match what exists
   - Testing conventions: framework, naming, file placement

5) Protected Areas — DO NOT TOUCH
   - NEVER read, reference, copy, log, or modify:
     .env, .env.*, config/secrets.*, *.pem, *.key — any secret/key material
   - Do not refactor auth/authentication modules without explicit instruction
   - Never modify existing DB migrations; only create new ones if instructed
   - Never modify CI/CD configs (.github/workflows, Jenkinsfile, docker-compose.prod.yml)
   - Never edit lockfiles (package-lock.json, yarn.lock, Gemfile.lock, poetry.lock) unless the task explicitly requires dependency changes
   - Treat generated/vendor/third-party code as read-only:
     dist/, build/, coverage/, vendor/, node_modules/, __pycache__/, .venv/ (if present)

6) AI Working Rules
   - For tasks touching 3+ files, produce a plan first:
     • files to change
     • intended edit per file (1-2 lines each)
     • risks or things that could break
   - Do not modify files outside the current task scope
   - Preserve existing patterns; prefer minimal diffs over refactors
   - Never replace working code with placeholder comments like "// ... rest of logic"
   - Ask before adding new dependencies or changing versions
   - When fixing a bug, explain what caused it before changing code
   - If unsure about a pattern or convention in this project, ask — don't guess
   - After changes, remind the user to run the project's test/lint/build commands. If you can identify them from config files, list the specific commands.

========================
FORMAT
========================
- Markdown with clear headings and short bullets
- Keep it under ~250 lines — concise and useful, not exhaustive
```
