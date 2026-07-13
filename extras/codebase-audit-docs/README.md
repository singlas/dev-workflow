# Codebase Audit & Documentation

A 3-prompt workflow for generating comprehensive documentation, running a codebase audit, and updating AI context files across a multi-repo project.

**See it in action** — two example outputs generated with these prompts:
[Sample Audit Report](https://www.shashanksingla.com/audit-report.html) ·
[Sample Documentation](https://www.shashanksingla.com/sample-documentation.html) ·
[overview page](https://www.shashanksingla.com/ai-dev-prompts.html)

## Prerequisites

- **GitHub CLI (`gh`)** — [Install](https://cli.github.com/) and authenticate with `gh auth login`
- **Access** — you (or the account running `gh`) must have read access to every repo you want in scope
- **AI coding assistant** — Claude Code, Cursor, Gemini CLI, or similar

## Setup

### 1. Create a workspace folder

```bash
mkdir ~/projects/my-platform && cd ~/projects/my-platform
```

### 2. Clone all repos

Use `gh` to clone every repo from your org/user:

```bash
# Clone all repos from an org
gh repo list <org-name> --limit 200 --json nameWithOwner -q '.[].nameWithOwner' | while read -r repo; do
  gh repo clone "$repo"
done
```

> **Tip:** If you only need a subset, clone them individually:
> ```bash
> gh repo clone <org>/repo-a
> gh repo clone <org>/repo-b
> ```

Make sure every repo is on its main/master branch and recently pulled.

### 3. Create a documentation repo

Create a new, empty repo to hold all cross-repo documentation and audit output:

```bash
gh repo create <org>/documentation --private --clone
```

This `documentation` repo is where all generated docs, audit reports, and architecture diagrams will live.

## Workflow

Run the prompts **in order** — each one builds on the output of the previous.

| Step | Prompt | What It Does |
|------|--------|-------------|
| 1 | [prompt-documentation.md](prompt-documentation.md) | Scans all repos, generates platform docs in the `documentation` repo |
| 2 | [prompt-audit.md](prompt-audit.md) | Reads generated docs + source code, produces audit reports in `documentation/audit/` |
| 3 | [prompt-context-update.md](prompt-context-update.md) | Uses docs + audit to update `.cursorrules` and `CLAUDE.md` in each repo |

### How to run

1. Open your AI assistant at the workspace root (the parent folder containing all repos)
2. Paste the contents of `prompt-documentation.md` → let it complete
3. Paste the contents of `prompt-audit.md` → let it complete
4. Paste the contents of `prompt-context-update.md` → let it complete
5. Review, commit, and push changes in each repo

## What You'll Get

After running all three prompts, your `documentation` repo will look like this:

```
documentation/
├── architecture/
│   └── architecture_current.jpg    # System architecture diagram
├── audit/
│   ├── executive-summary-action-plan.md
│   ├── security-audit.md
│   ├── code-quality-architecture.md
│   ├── performance-audit.md
│   ├── error-documentation.md
│   ├── third-party-integrations.md
│   ├── infrastructure-ci-cd.md
│   ├── testing-coverage.md
│   └── documentation-audit.md
├── operations/
│   ├── technical-architecture-api-reference.md
│   ├── database-schema-documentation.md
│   ├── aws-operations-runbook.md
│   └── background-jobs-task-guide.md
├── CLAUDE.md
├── README.md                       # Platform overview with repo table
└── handover-checklist.md
```

Here's an example of what a completed documentation repo looks like on GitHub:

![Example documentation repo on GitHub](../site/assets/example-documentation-repo.png)

## Bonus: Architecture Diagram

After documentation is generated, ask your AI session to create an architecture diagram prompt. For example:

> "Based on the documentation you just generated, write me a prompt I can paste into Google Gemini (with image generation) to create a visual system architecture diagram showing all services, databases, external integrations, and how they connect."

This produces a detailed prompt you can use with Gemini to generate a diagram like this:

![Example architecture diagram generated with Gemini](../site/assets/example-architecture-diagram.png)

Save the generated diagram as `architecture/architecture_current.jpg` in your documentation repo.
