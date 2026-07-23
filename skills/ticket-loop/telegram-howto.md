🤖 How to work with this group

TICKETS
• take ABC-123 (or "ABC-123 go") — queue an existing board ticket for the agent
• flag: <title> — file a ticket for human review; the agent won't build it
• Reply to the agent's ❓ to answer its question — the reply routes to the right ticket and unblocks it
• go/yes or skip/no — answer a build proposal
• Attach a screenshot to any message as evidence

ASK THE CODEBASE
• question: <anything about the code> — a read-only agent answers here; no ticket is created
• In a multi-repo group, prefix [repo] to target a specific repo

RELEASES
• release — the agent cuts the base→prod release PR for this repo
• release <repo> — same, for a specific repo in a multi-repo group
• Merging that PR on GitHub is what deploys — the agent never merges it

HOUSEKEEPING
• questions — list the agent's open questions
• prune questions — clear questions whose tickets were closed elsewhere
• A daily digest posts automatically with merged/pending/blocked work

The agent works queued tickets one at a time, opens one PR per ticket into the
integration branch, and babysits its PRs (CI, review comments, merge conflicts)
until they merge. It asks here whenever a ticket lacks information.
