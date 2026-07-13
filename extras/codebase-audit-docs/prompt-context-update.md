# Prompt: Update Context Files

> Run this AFTER the documentation and audit prompts have been completed. 
> Updates .cursorrules and CLAUDE.md in each repo using the generated 
> documentation and audit findings.

---

## Instructions for AI

You have access to freshly generated documentation (docs/) and audit 
reports (audit/) for this project. Your job is to update the AI context 
files in each repository so they reflect the current state of the codebase.

### Process

1. Read all files in docs/ and audit/ directories.
2. Read the existing .cursorrules and CLAUDE.md in each repo.
3. Update each file using the process below.
4. Do NOT delete existing rules or conventions that are still accurate 
   — merge new context into what's already there.

### For each repo, update .cursorrules with:

- **Project architecture** section reflecting the current documentation 
  (replace if outdated, keep if accurate)
- **This repo's role** updated with any findings from the audit 
  (tech debt, coverage gaps, known issues)
- **Cross-repo dependencies** updated from the documentation's 
  architecture and API reference
- **Coding conventions** validated against what the audit actually 
  found in the codebase (not aspirational — what's actually used)
- **Known issues** section added or updated from audit findings 
  relevant to this specific repo
- **Testing state** from the testing coverage audit 
  (what exists, what's missing, priority targets)

### For each repo, update CLAUDE.md with:

- Same content as .cursorrules
- Add links to all generated documentation and audit reports 
  at the top of the file
- Add a "Last updated" date

### Quality checks

- Every .cursorrules should have the same "Project Architecture" 
  section across all repos in the project
- File paths and endpoint references should match actual source code
- No real credentials or secrets in any generated file
- Existing rules that are still valid should be preserved, 
  not removed