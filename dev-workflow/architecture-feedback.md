# Architecture Feedback And Adoption Recommendation

## Short verdict

The core idea is strong. The repo has a real point of view and solves the right
problem: not "make the model code", but "operationalize coding work safely".

What exists today is closer to a serious internal platform primitive than a
polished product. The workflow architecture is the differentiator. The current
implementation is still brittle in the way shell-heavy orchestration systems
usually are.

If the goal is to get real internal use plus a few friendly teams using it, the
best path is usually:

- keep this repo and its opinionated workflow model
- harden it enough for actual use
- avoid a full ground-up framework rewrite right now
- selectively borrow stronger runtime pieces later

Do not throw this away yet. Also do not pretend it is already a mature product.

## What this repo gets right

- The three-zone split is correct: framework, repo config, injected runtime
  secrets/state.
- "Config can tighten but never loosen" is a strong safety principle.
- PR-per-ticket and worktree isolation map well to how teams actually absorb AI
  output.
- The repo is policy-first, not model-first. That is the right instinct.
- The automation is aimed at the real pain: queue selection, branch hygiene,
  approvals, review handling, and PR lifecycle.

## What is weak today

- Too much critical behavior lives in English skills plus bash glue.
- Policy is spread across docs, skills, scripts, and config validation.
- The adapter seam is promising but not yet truly productized.
- Headless unattended paths are not mature enough to fully trust without care.
- The system is more "well-designed prototype" than "boring reliable platform".

## Architectural feedback

### 1. Keep the workflow opinion, reduce implementation informality

The opinionated workflow is the valuable thing here. Keep that.

What should change is the execution layer: move away from shell scripts owning
the important state transitions.

### 2. Build a small typed control plane

The next durable layer should be a small Python or Go engine that owns:

- ticket state
- run state
- approvals
- blockers
- worktree lifecycle
- PR lifecycle
- policy checks
- adapter calls

Shell can remain as thin wrappers, not the source of truth.

### 3. Separate policy from execution

Right now policy is conceptually strong but mechanically distributed.

A better split:

- policy engine decides what is allowed
- orchestrator decides what to do next
- adapters talk to Linear/GitHub/Telegram
- runners execute concrete steps

That will make the system easier to test, audit, and explain.

### 4. Add durable state and replay

Even if it starts with SQLite, the system wants:

- an event log
- resumable runs
- reproducible decision history
- replay/simulation from recorded inputs

That is the line between "agent automation" and "operable platform".

### 5. Treat integrations as event sources/sinks

Telegram, Linear, and GitHub should not carry orchestration logic. They should
just provide events and receive actions.

That makes the adapter layer real instead of aspirational.

## Comparison with external options

### If you want a managed product

Devin is ahead on product completeness: hosted sessions, broader integrations,
automations, scheduled sessions, and a clearer path for teams that want a
service rather than a framework.

### If you want an open-source agent platform

OpenHands is the stronger external base. It is more framework-like, supports
cloud and enterprise shapes, and is architected more explicitly as a platform.

### If you want orchestration primitives

LangGraph is stronger as a runtime for long-running, stateful,
human-in-the-loop agents.

### If you want durability more than "agent framework"

Temporal is the strongest foundation for crash-proof workflow execution.
Prefect is an easier, more ergonomic middle ground.

## Recommendation by goal

### Goal: real internal use + a few friendly teams soon

Continue building on this repo.

Reason:

- your differentiator is the workflow opinion
- swapping to another framework now will mostly delay adoption
- you do not yet need a grand platform rewrite
- you do need reliability hardening and tighter boundaries

Practical version:

- keep the current surface area
- fix the brittle runner paths
- add stronger tests around git/worktree/reset/PR behavior
- centralize the highest-risk state transitions into typed code
- delay deep policy-engine work until usage gives clearer pressure

### Goal: become a general external platform product

Then the current implementation is too informal underneath. For that path, you
should either:

- rebuild the core around a typed durable engine, or
- adopt a stronger orchestration substrate like LangGraph or Temporal under
  your workflow layer

### Goal: hobby project with occasional use

Then staying here is fine. Just be honest that it is an opinionated automation
tool, not yet a platform.

## Direct answer to the "move external or continue here?" question

If the goal is simply to get people using it internally, among friends, and in
a few teams, continue here.

Do not switch to an external framework yet unless one of these becomes true:

- you need strong multi-tenant hosted operation
- you need durable resumability across many long-running jobs
- you need auditability and replay that bash can no longer support
- you want to sell a platform rather than operate an opinionated workflow tool

The better move is:

1. keep this repo as the product surface
2. harden the runner and state model
3. move the risky parts from bash into typed code over time
4. do the deeper policy/runtime architecture incrementally as usage justifies it

That gives you real adoption sooner without throwing away the part that is
actually differentiated.
