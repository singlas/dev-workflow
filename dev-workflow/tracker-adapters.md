# Tracker adapters — the provider seam

The skills and the autonomous loop never talk to a tracker directly. They
talk in **canonical verbs**, and a thin per-provider adapter maps each verb
onto that tracker's API. Today there is one implementation — **Linear**, via
its MCP server — but every skill is written against the verbs below, not
against Linear, so a second provider is a new mapping table, not a rewrite.

**One hard rule: state and label names always come from `tracker.roles` in
`dev-workflow.yml`.** A skill must never hardcode `agent`, `Todo`, `Done`,
`agent-blocked`, etc. It resolves the *role* (`queue`, `blocked`, `exclude`,
`done`) to the repo's own names at runtime — read them with
`dw-config.py`, e.g. `python3 dev-workflow/dw-config.py dev-workflow.yml
tracker.roles.queue.label`. That is what lets the same skill drive two repos
whose boards use different words.

## Canonical verbs

| Verb | Inputs | Semantics |
|---|---|---|
| `list_actionable` | `roles.queue` (label + states), `roles.exclude.labels` | The work queue: tickets carrying the queue label, in one of the queue states, that carry none of the excluded labels. This is what a loop pass iterates. |
| `get_ticket` | ticket key (`ABC-123`) | Full ticket — title, description, current state, labels, comments, linked PRs. |
| `create_ticket` | title, body, `[labels]`, `[state]` | Open a new ticket (e.g. a follow-up the agent spun off). |
| `comment` | ticket key, markdown body | Append a comment — clarifying questions, answers recorded back, status notes. |
| `move` (state-role) | ticket key, **state role** (`done`, or a queue state) | Advance lifecycle by *role*, resolved to the board's state name. Never pass a literal state. |
| `label` / `unlabel` (label-role) | ticket key, **label role** (`queue`, `blocked`, an `exclude` label) | Add/remove a role's label, resolved to the board's label name. E.g. set `blocked` when a ticket needs a human; clear `queue` when done. |
| `link_pr` | ticket key, PR URL | Attach the opened PR to the ticket so the two are cross-referenced. |

## Linear mapping (the implementation today)

Linear is driven through its MCP tools (`mcp__linear__*`). Pass the **team
name** from `tracker.team` (Linear's `list_*` tools want the human team name,
not the key prefix). Names below in `roles.*` are read from `dev-workflow.yml`.

| Verb | Linear MCP call | Notes |
|---|---|---|
| `list_actionable` | `mcp__linear__list_issues` | Filter by `team = tracker.team`, `label = roles.queue.label`, `state ∈ roles.queue.states`; then drop any issue carrying a `roles.exclude.labels` entry (filter client-side — combine as needed). |
| `get_ticket` | `mcp__linear__get_issue` | By issue id / key. |
| `create_ticket` | `mcp__linear__save_issue` | Omit the id to create; set `team`, `title`, `description`, `labels`, `state`. |
| `comment` | `mcp__linear__save_comment` | New comment on the issue. |
| `move` (state-role) | `mcp__linear__save_issue` | Update the existing issue's `state` to the name resolved from the role (e.g. `roles.done.state`). |
| `label` / `unlabel` (label-role) | `mcp__linear__save_issue` | Update the issue's `labels` set — add/remove the name resolved from the role. |
| `link_pr` | `mcp__linear__create_attachment` | Attach the PR URL to the issue. |

**Linear MCP has no delete.** The strongest teardown is moving an issue to a
`Canceled` state — never assume a hard delete exists. Anything the loop
"removes" is a state/label change, not a deletion.

## Adding a provider

To wire a second tracker, add its name to `KNOWN_TRACKERS` in `validate.py`
and write a mapping table like the one above — implement each canonical verb,
resolving every state/label from `tracker.roles`, never hardcoding names.

**GitHub Issues sketch** (illustrative):

- **Labels → labels.** The `queue` / `blocked` / `exclude` roles map straight
  onto GitHub issue labels (`roles.queue.label` = e.g. `agent`).
- **States → open/closed + labels.** GitHub issues have only `open`/`closed`,
  so multi-step lifecycle rides on labels: the queue states become label
  presence on an open issue; `roles.done.state` maps to closing the issue
  (optionally with a `done` label). `list_actionable` = open issues with the
  queue label and without any exclude label.
- **Verbs → API.** `get_ticket` = `gh issue view`; `comment` = `gh issue
  comment`; `create_ticket` = `gh issue create`; `move`/`label` = `gh issue
  edit` (labels) or `gh issue close`; `link_pr` = a comment or the PR body's
  `Closes #N`.

Keep the shape identical to the Linear table so a skill written to the verbs
runs unchanged against either provider.
