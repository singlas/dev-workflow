# Prompt: Codebase Audit

> Use this prompt with Claude Code (or similar AI coding assistant) to run a comprehensive codebase audit across one or more repositories. Produces an executive summary with scorecard and detailed per-area reports.

---

## Prerequisites

Run this from a parent directory containing all project repos. Ensure all repos are on their main/master branch and recently pulled.

## Instructions for AI

You are conducting a codebase audit for a multi-repo software platform. The audit is an objective technical report intended for founders and stakeholders — not a task list for the development team. Be factual, reference specific files and line numbers, and avoid defensive or apologetic framing.

### Setup

1. Identify all repositories in scope.
2. Read every settings file, config file, CI/CD workflow, and dependency manifest.
3. Read environment/secrets files if provided (do NOT include real credential values in any output).
4. Ask the user for context: team size, how long the codebase has been maintained, any known constraints.

### Reports to Create

Create all reports in an `audit/` subdirectory. Each report is a standalone markdown file.

#### 1. `audit/executive-summary-action-plan.md` — Executive Summary

Write this LAST, after all other reports are complete. Structure:

```markdown
# Platform — Audit Summary & Action Plan
> Date: YYYY-MM-DD | Scope: repo-a, repo-b, repo-c

## Executive Summary
One paragraph: what was reviewed, team context.

### Scorecard
| Area | Score | For a Small Startup Team | Path to Improvement | What It Means |
Use /10 scoring. Include adjusted score for team size. "Path to Improvement" indicates
whether fixes are easy config changes, incremental refactoring, or fundamental rework.
State findings factually — do not justify or defend gaps.

### Top 5 Strengths
Numbered list of what the codebase does well.

### Top 5 Risks
Numbered list of the most impactful issues.

## Platform Architecture
Architecture diagram (or reference to one) + brief description of tier separation
and communication patterns.

## [Per-Area Sections]
For each audit area: **Highlights** (what works) and **Concerns** (what doesn't).
Include the score in the heading: "## Security — 4/10"

## Action Plan
Table of prioritized items organized by sprint/phase:
| # | Action | Area | Effort |
Mark as "findings from the audit — not prescriptive assignments."

## Appendix: Audit Methodology
Document: process (scope → exploration → documentation → scoring), what was reviewed,
what was NOT reviewed (production metrics, pen testing, etc.), tools used.
```

#### 2. `audit/security-audit.md` — Security
- Secrets management: how credentials are stored, rotated, isolated per environment
- Authentication: token type, expiry, storage (localStorage vs httpOnly cookies), permission enforcement
- CORS / CSRF / headers: configuration per environment, exemptions
- XSS surface: `dangerouslySetInnerHTML`, unsanitized user input rendering
- Public endpoints: which routes are unauthenticated and why
- Error message leakage: does `str(e)` or stack traces reach API clients
- Information disclosure: debug tools in production, verbose error pages
- Dependency vulnerabilities: known CVEs in current versions

#### 3. `audit/code-quality-architecture.md` — Code Quality & Architecture
- Overall architecture: tier separation, communication patterns, async processing
- App/module structure: how the codebase is organized
- God files/modules: files over 500-1000 lines, modules doing too much
- Naming consistency: conventions followed or broken, typos
- Dead code: TODOs, FIXMEs, commented-out code, print/console.log statements
- Type safety: type hints (Python), TypeScript strictness, `any` usage
- Error handling patterns: exception catching, custom error classes
- Code duplication: copy-pasted patterns that should be abstracted
- Known business logic debt: incomplete implementations, TODOs with real impact

#### 4. `audit/performance-audit.md` — Performance
- Database: connection pooling, query optimization (N+1, select_related), pagination, indexing
- Caching: what's cached, cache backend, TTLs, missed opportunities
- Async processing: worker config, concurrency, task routing, queue separation
- Frontend: bundle size, code splitting, lazy loading, dev tools in prod
- API patterns: retry logic, request deduplication, rate limiting
- Infrastructure: single points of failure, scaling constraints
- Note: state clearly that production metrics were not reviewed if that's the case

#### 5. `audit/error-documentation.md` — Error Handling
- Backend: exception handler, response format, error codes, logging setup
- Frontend: error boundaries, error monitoring (Sentry etc.), API error handling
- Per-app error handling patterns
- Error response format reference
- Monitoring gaps: which errors are invisible

#### 6. `audit/third-party-integrations.md` — Third-Party Integrations
- Per-service inventory table: service, package/version, auth method, files involved, env vars
- Dependency version audit: outdated packages, EOL frameworks, known CVEs
- Blast radius assessment: what's exposed if each credential is compromised
- Single points of failure: shared credentials, single API keys

#### 7. `audit/infrastructure-ci-cd.md` — Infrastructure & CI/CD
- CI/CD pipelines: what exists per repo, what runs (lint, test, deploy), what's missing
- Deployment process: automated vs manual, environments, rollback capability
- Containerization: Dockerfiles, docker-compose, or lack thereof
- Infrastructure as Code: Terraform, CloudFormation, or manual setup
- Environment parity: differences between dev/staging/prod

#### 8. `audit/testing-coverage.md` — Testing
- Test inventory: unit, integration, E2E — what exists vs what's empty
- Testing frameworks: installed vs actually used
- CI test execution: do any pipelines run tests
- Coverage gaps: critical paths with no tests
- Priority testing targets: what should be tested first

#### 9. `audit/documentation-audit.md` — Documentation
- README quality per repo
- API documentation: Swagger/OpenAPI, Postman, or none
- Inline comments: density and quality
- Architecture documentation
- Onboarding assessment: how long for a new developer to be productive

#### 10. `audit/blockchain-audit.md` (if applicable)
- Transaction flow: how on-chain operations are triggered and executed
- Smart contracts: what's deployed, where source lives
- Wallet/key management: how private keys are stored and used
- Error handling: retries, failed transaction recovery
- Monitoring: alerting on failures, balance tracking

### Scoring Guidelines

| Score | Meaning |
|-------|---------|
| 9-10 | Industry best practice. Few or no issues. |
| 7-8 | Solid. Minor gaps that don't pose risk. |
| 5-6 | Functional but with notable gaps. Works for current scale. |
| 3-4 | Significant gaps. Risks exist that need addressing. |
| 1-2 | Critical gaps. Major risk area. |

For "Small Startup Team" adjusted score: add 1-2 points where the gap is clearly due to team size/time constraints rather than poor decisions. Do not adjust for gaps that would exist regardless of team size (e.g., shared credentials, no error monitoring).

### Tone Guidelines

- **Be objective.** State what is and what isn't. Do not editorialize.
- **No defensive framing.** Do not write "For a solo developer, this is understandable" or "This is expected given the team size." The adjusted score column handles context — the prose should be neutral.
- **No task assignment.** This is a report, not a sprint plan. The action plan lists findings; it doesn't assign them to anyone.
- **Reference specifics.** File paths, line numbers, package versions, configuration values. Vague findings are useless.
- **No real secrets.** Never include actual API keys, passwords, tokens, or credentials in any report.

### Process

1. If documentation was generated from Prompt 1, read all generated docs before starting the audit. Reference the documentation where relevant rather than re-describing architecture.
2. Read all repos thoroughly before writing anything. Scan: settings, configs, CI/CD, dependencies, env files, model files, view/controller files, test files, README files.
3. Create a plan listing all reports and key findings per area.
4. Write detailed reports first (security, code quality, etc.).
5. Write the executive summary LAST — it synthesizes the detailed reports.
6. Review all files for: real credential values (remove), defensive language (rewrite), factual accuracy.
7. Skip section 10 (Blockchain Audit) unless the project has blockchain/smart contract components.
8. Update `CLAUDE.md` and `README.md` to link to the audit reports.
