# Prompt: Project Handover Checklist

> Use this prompt with Claude Code (or similar AI coding assistant) to generate a comprehensive handover checklist for transferring a project to a new team or developer. Produces a structured document covering credentials, access, files, and verification steps.

---

## Instructions for AI

You are creating a project handover checklist. This document ensures nothing is missed when transferring ownership of a multi-repo software platform. The output should be a single markdown file that can be shared with both the outgoing and incoming parties.

### Setup

1. Read all repositories in scope — focus on: settings files, environment variables, deployment configs, CI/CD workflows, and third-party service integrations.
2. Read any existing documentation (architecture docs, runbooks, audit reports).
3. If an audit has already been run, reference its findings — the handover should address the top risks identified.
4. Ask the user: who is handing over, who is receiving, what's the timeline, and are there any pending items (bugs, features in progress).

### Document to Create

#### `handover-checklist.md`

```markdown
# Project Handover Checklist
> Project: [Name] | From: [Team/Person] | To: [Team/Person] | Date: YYYY-MM-DD

## 1. Files to Transfer from Production Servers

Table of every file that lives on production servers (not in repos) and needs
to be transferred:

| # | File | Location on Server | Contains | Transfer Method |
|---|------|--------------------|----------|-----------------|
| 1 | local_settings.py | /path/on/server | All production env vars | SCP / secure transfer |
| 2 | firebase_creds.json | /path/on/server | Firebase service account | SCP / secure transfer |
| ... | | | | |

Generate this by scanning: settings files for references to external config files,
credential file paths, SSL certs, nginx configs, supervisor configs.

## 2. Account Access to Transfer

Table of every third-party service that needs account access transferred:

| # | Service | What to Transfer | Current Access | Action Required |
|---|---------|-----------------|----------------|-----------------|
| 1 | AWS | IAM/root access — all infrastructure | Console + programmatic | Create new IAM user or transfer account |
| 2 | GitHub | Admin access to all repos + Actions secrets | Org membership | Invite to org as owner |
| 3 | Stripe | Dashboard + API keys | Team member | Add as team admin |
| ... | | | | |

Generate by scanning: all env vars that reference external services, all package
dependencies that require API keys, CI/CD secrets, deployment targets.

## 3. Credentials Inventory

Table of every credential/secret used by the application:

| # | Category | Credential | Where It's Used | Where It's Stored |
|---|----------|-----------|-----------------|-------------------|
| 1 | Django Core | SECRET_KEY | Sessions, CSRF, signing | local_settings.py |
| 2 | Database | DB host/port/user/password | PostgreSQL connection | local_settings.py |
| 3 | AWS | Access Key + Secret | S3, SES, Lambda | local_settings.py |
| ... | | | | |

Group by: Core/Framework, Database, Cloud Provider, Payments, Auth/Social,
Communication, Blockchain, Monitoring.

Do NOT include actual credential values — only describe what they are and where
they're stored.

## 4. Infrastructure Inventory

| Component | Service/Provider | Access Method | Notes |
|-----------|-----------------|---------------|-------|
| Backend server | AWS EC2 | SSH (key-based) | Instance ID, region |
| Database | AWS RDS | Via backend server | Instance class, engine |
| File storage | AWS S3 | AWS Console | Bucket names |
| CDN | AWS CloudFront | AWS Console | Distribution IDs |
| ... | | | |

## 5. Domain & DNS

| Domain | Registrar | DNS Provider | Records to Know |
|--------|-----------|-------------|-----------------|
| example.com | Registrar X | Route 53 | A, CNAME for subdomains |

## 6. Post-Transfer Verification Checklist

Steps the receiving team should run to verify everything works:

- [ ] Can access all GitHub repos (clone, push)
- [ ] Can SSH into production servers
- [ ] Can access AWS Console
- [ ] Can access database (via SSH tunnel or direct)
- [ ] Local development environment runs successfully
- [ ] Can deploy to staging
- [ ] Can deploy to production
- [ ] Can access all third-party dashboards (Stripe, Shopify, etc.)
- [ ] Can view application logs
- [ ] Can trigger and monitor background jobs
- [ ] Webhook endpoints are receiving events
- [ ] Email sending works

## 7. Credential Rotation Plan

After handover, these credentials should be rotated (new values generated):

| Credential | Why Rotate | How to Rotate | Impact of Rotation |
|-----------|-----------|---------------|-------------------|
| Django SECRET_KEY | Shared with outgoing team | Generate new random key, restart server | Invalidates existing sessions |
| AWS Access Keys | Shared with outgoing team | Create new IAM user, update server config | Update all services using the key |
| ... | | | |

## 8. Known Issues & In-Progress Work

| Item | Status | Notes |
|------|--------|-------|
| [Bug/feature description] | In progress / Blocked / Known issue | Context |

Pull from: audit report risks, open GitHub issues, TODO items in code.

## 9. Key Contacts

| Role | Name | Contact | Access To |
|------|------|---------|-----------|
| Outgoing developer | | | Full system knowledge |
| Account owner (AWS) | | | Infrastructure |
| Account owner (Stripe) | | | Payments |

## 10. Reference Documents

| Document | Location | Description |
|----------|----------|-------------|
| Platform Documentation | /path or URL | Architecture, API reference, setup guides |
| Audit Report | /path or URL | Codebase audit with scorecard and action plan |
| Operations Runbook | /path or URL | AWS operations, deployment, troubleshooting |
```

### Process

1. Scan all repos and documentation to build the complete inventory.
2. Cross-reference with any existing audit report — the audit's third-party integrations and security findings will identify most credentials and services.
3. Present the plan to the user before writing — they may know about services or credentials not visible in code.
4. Write the document.
5. Review for completeness: every env var should map to a credential, every third-party service should have an account access entry, every server file should be listed.
6. Do NOT include real credential values anywhere in the document.

### Tone

- Checklist format — scannable, actionable
- Each item should be clear enough that someone unfamiliar with the project can follow it
- Group related items together
- Use checkboxes where the receiving team needs to verify something
- Be explicit about what needs to happen vs what's already done
