# Antigravity Rules Generator — Google Antigravity / Firebase Studio

> **Use case:** Projects developed in [Google Antigravity](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/), Google's agentic development platform (successor to Firebase Studio / Project IDX).

## How Antigravity Rules Work

Antigravity uses a **modular rules system** stored in `.agent/rules/`. Each rule is a Markdown file with an activation mode that controls when it's loaded into context.

### Activation Modes

| Mode | When it loads | Use for |
|---|---|---|
| **Always On** | Every prompt | Project overview, security rules, core conventions |
| **Glob Pattern** | When editing files matching a pattern (e.g., `**/*.test.ts`) | Language/domain-specific rules |
| **Model Decision** | Agent decides based on task context | Specialized workflows (deployment, DB ops) |
| **Manual** | Only when explicitly referenced via `@rule-name` | Rarely-needed reference material |

### Storage

- **Workspace rules:** `.agent/rules/*.md` in project root
- **Global rules:** `~/.gemini/GEMINI.md` (shared with Gemini CLI — [known conflict](https://github.com/google-gemini/gemini-cli/issues/16058), keep project rules in `.agent/rules/` to avoid issues)

## How to Use

1. Open your project in Antigravity
2. Create the rules directory: `mkdir -p .agent/rules`
3. Open Agent chat and paste the prompt below
4. **Use the best model available** (Gemini 2.5 Pro) — smaller models skip sections or hallucinate
5. Save each generated block as a separate `.md` file in `.agent/rules/`
6. Set the activation mode for each file (via Editor → `...` → Customizations → Rules)
7. Review each file — verify stack versions, conventions, and protected areas
8. **Security check:** confirm `.env`, credentials, and auth modules are in `security-rules.md`
9. Commit to git and push

### Tips

- **Activation modes matter:** don't set everything to "Always On" — use Glob patterns for language-specific rules and Model Decision for specialized workflows
- Keep rules focused — 30-80 lines per file, one concern per file
- Update rules when you add new libraries or change architecture
- If the AI marked something as "Unknown" — fill it in manually
- **Gemini CLI users:** Antigravity rules and Gemini CLI both use `~/.gemini/GEMINI.md` for global context. Keep project-specific rules in `.agent/rules/` to avoid conflicts.
- **Cursor users:** this system is very similar to `.cursor/rules/*.mdc` — see [`cursorrules-large-repo.md`](./cursorrules-large-repo.md)

## The Prompt

Paste this into Antigravity Agent chat.

---

```
Scan this project and generate a set of modular rule files for the `.agent/rules/` directory.

HARD RULE: Base everything on actual repository contents. If something can't be
determined from files present, write "Unknown" — do not guess.

For each file, specify the recommended Activation Mode in a comment at the top.

========================
FILES TO GENERATE
========================

1. project-context.md (Activation: Always On)
   - 1-2 line overview of the project and end user
   - Stack & Versions: languages, frameworks, major libraries — exact versions from configs
   - Primary build, test, and lint commands
   - If a major framework is detected (e.g., Next.js 14 App Router, Django REST, Rails 7,
     Flutter, Angular), note it explicitly so the agent prioritizes its patterns

2. structure-and-examples.md (Activation: Always On)
   - Map of key directories and their purpose
   - Core entrypoints (main server, app root, CLI entry)
   - Identify 2 "canonical" example files — the gold standard for code in this repo

3. security-rules.md (Activation: Always On)
   - Strict DO NOT TOUCH list:
     .env, .env.*, config/secrets.*, *.pem, *.key — any secret/key material
   - Do not refactor auth/authentication modules without explicit instruction
   - Never modify existing DB migrations; only create new ones if instructed
   - Never modify CI/CD configs unless explicitly instructed
   - Never edit lockfiles unless the task explicitly requires dependency changes
   - Mark generated/vendor/third-party dirs as read-only:
     dist/, build/, coverage/, vendor/, node_modules/, __pycache__/, .venv/

4. coding-standards.md (Activation: Always On)
   - Naming conventions inferred from existing code (camelCase, snake_case, PascalCase, kebab-case)
   - Component style: functional vs class, hooks patterns (if applicable)
   - Import ordering and export style (named vs default)
   - Type strictness: strict types, `any`, or no types?
   - Error handling patterns: early returns, try/catch, custom error classes — match what exists
   - Testing conventions: framework, naming, file placement

5. agent-behavior.md (Activation: Always On)
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
   - After changes, list the test/lint/build commands the user should run

6. [domain-specific].md files (Activation: Glob Pattern)
   - If the project has distinct domains (e.g., /frontend, /backend, /infra, /mobile):
     create one targeted rule per domain with a glob pattern
   - Example: frontend-rules.md with glob: "frontend/**", "packages/ui/**"
   - Include domain-specific conventions, key libraries, and patterns
   - Map cross-service dependencies ("frontend calls backend API at /api/v1/*")
   - If an OpenAPI spec, GraphQL schema, or API contract exists, reference its path

7. [workflow-specific].md files (Activation: Model Decision)
   - If the project has specialized workflows that don't apply to every task:
   - Example: database-ops.md — migration commands, seed data, backup/restore
   - Example: deployment.md — deploy commands, environment topology, rollback procedures
   - Use "Model Decision" activation so the agent loads these only when relevant

========================
FORMAT
========================
- Each file should start with a comment indicating the recommended activation mode:
  <!-- Activation: Always On -->
  or
  <!-- Activation: Glob Pattern: "frontend/**" -->
  or
  <!-- Activation: Model Decision -->
- Markdown with clear headings and short bullets
- Keep each file focused — 30-80 lines per file
- Output all files in sequence, clearly labeled so the user can copy each one

========================
HARD RULES
========================
- Do NOT assume versions from memory; only use what is declared in the repo
- If a major framework is detected, note it explicitly
- For monorepos: identify the workspace config (npm workspaces, pnpm-workspace.yaml,
  lerna.json, turborepo turbo.json) and document cross-package relationships
- If Google/Firebase services are detected (Firestore, Cloud Functions, Firebase Auth,
  Cloud Run, etc.), note them explicitly — Antigravity has deep Firebase integration
```
