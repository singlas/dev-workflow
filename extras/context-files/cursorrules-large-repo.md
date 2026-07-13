# .cursor/rules/ Generator — Large & Complex Repos

> **Use case:** Monorepos, multi-service codebases, or any project where a single `.cursorrules` file becomes too heavy.
> For simpler single-repo projects, see [`cursorrules-small-repo.md`](./cursorrules-small-repo.md).

## Why Modular Rules?

Cursor supports splitting rules into multiple `.mdc` files inside `.cursor/rules/`. Each file can target specific file patterns via `globs`, so the AI only loads rules relevant to what you're editing — no context drift.

| | Single `.cursorrules` | Modular `.cursor/rules/*.mdc` |
|---|---|---|
| **Structure** | All-in-one | Split by concern |
| **Triggering** | Always loaded | Context-aware via `globs` |
| **Format** | Plain Markdown | Markdown + YAML frontmatter |
| **Scalability** | Gets noisy past ~150 lines | Scales with project complexity |
| **Rule adherence** | Higher risk of AI skipping rules | Better adherence — fewer, focused rules per file |

## How to Use

1. Open your project in Cursor
2. Run `mkdir -p .cursor/rules` in the project root
3. Open Chat mode (Cmd+L / Ctrl+L) — use `@Codebase` so Cursor indexes the full project
4. Paste the prompt below
5. **Use the best model available** (Claude Sonnet/Opus or GPT-4o) — smaller models skip sections or hallucinate versions
6. Save each generated block as a separate `.mdc` file inside `.cursor/rules/`
7. Review each file — verify stack versions, conventions, and protected areas are correct
8. **Security check:** confirm `.env`, credentials, keys, and auth modules are listed in `security-and-protected.mdc`
9. Commit the `.cursor/rules/` directory to git and push

### Tips

- **Plan Mode enforcement:** if the AI starts writing code immediately on a complex task, tell it "Follow ai-behavior.mdc and give me a plan first"
- **Keep rules updated:** when you adopt a new library or change architecture, update the relevant `.mdc` file
- **Personal rules:** create your own `.mdc` files for personal workflows and add them to `.gitignore`
- **Monorepo globs:** use targeted globs like `frontend/**/*.tsx` or `services/auth/**` to scope rules to specific packages
- If the AI marked something as "Unknown" — that's good, it didn't guess. Fill it in manually.
- The legacy `.cursorrules` file still works — you can migrate incrementally

## The Prompt

Paste this into Cursor Chat with `@Codebase` enabled.

---

```
@Codebase Scan this project and generate a set of modular rule files for the `.cursor/rules/` directory.

HARD RULE: Base everything on actual repository contents. If something can't be determined from files present, write "Unknown" — do not guess.

For each file below, include a YAML frontmatter block with 'description' and 'globs' or 'alwaysApply'.

========================
FILES TO GENERATE
========================

1. project-context.mdc (alwaysApply: true)
   - 1-2 line overview of the project and end user
   - Stack & Versions: languages, frameworks, major libraries — with exact versions from lockfiles/configs
   - Primary build, test, and lint commands

2. structure-and-examples.mdc (alwaysApply: true)
   - Map of key directories and their purpose
   - Identify 2 "canonical" example files that represent the gold standard for code in this repo
     (a well-written component, service, API route, or test)

3. security-and-protected.mdc (alwaysApply: true)
   - Strict DO NOT TOUCH list:
     .env, .env.*, config/secrets.*, *.pem, *.key — any secret/key material
   - Do not refactor auth/authentication modules without explicit instruction
   - Never modify existing DB migrations; only create new ones if instructed
   - Never modify CI/CD configs (.github/workflows, Jenkinsfile, docker-compose.prod.yml)
   - Never edit lockfiles unless the task explicitly requires dependency changes
   - Mark generated/vendor/third-party dirs as read-only:
     dist/, build/, coverage/, vendor/, node_modules/, __pycache__/, .venv/

4. coding-standards.mdc (alwaysApply: true)
   - Naming conventions inferred from existing code (camelCase, snake_case, PascalCase, kebab-case)
   - Component style: functional vs class, hooks patterns (if applicable)
   - Import ordering and export style (named vs default)
   - Type strictness: strict types, `any`, or no types?
   - Error handling patterns: early returns, try/catch, custom error classes — match what exists
   - Testing conventions: framework, naming, file placement

5. ai-behavior.mdc (alwaysApply: true)
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
   - After changes, remind the user to run the project's test/lint/build commands

6. [domain-specific].mdc files (targeted globs)
   - If the project is a monorepo or has distinct domains (e.g., /frontend, /backend, /infra, /mobile):
     create one targeted .mdc per domain using globs
   - Example: frontend.mdc with globs: "frontend/**", "packages/ui/**"
   - Include domain-specific conventions, key libraries, and patterns
   - Map cross-package dependencies ("frontend calls backend API at /api/v1/*")
   - If an OpenAPI spec, GraphQL schema, or API contract exists, reference its path

========================
FORMAT
========================
- Each file should start with YAML frontmatter:
  ---
  description: Short description of what this rule file covers
  globs: "pattern/**" (or use alwaysApply: true)
  ---
- Markdown body with clear headings and short bullets
- Keep each file focused — 30-80 lines per file
- Output all files in sequence, clearly labeled so the user can copy each one

========================
HARD RULES
========================
- Do NOT assume versions from memory; only use what is declared in the repo
- If a major framework is detected (e.g., Next.js 14 App Router, Django REST, Rails 7),
  note it explicitly so the AI prioritizes that framework's patterns over generic ones
- For monorepos: identify the package manager workspace config
  (npm workspaces, pnpm-workspace.yaml, lerna.json, turborepo turbo.json)
  and document cross-package dependency relationships
- If deployment topology is evident (docker-compose, k8s manifests, serverless configs),
  document which service talks to what
```
