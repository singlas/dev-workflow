# Skill: cleanup — session closer (feature→base PR)

> **This is now a real, installable plugin skill:
> [`skills/cleanup/SKILL.md`](../../skills/cleanup/SKILL.md).**
> Install it via the `dev-workflow` plugin, or copy `skills/cleanup/` into your
> repo's `.claude/skills/`. It is config-driven — the base branch, test/lint
> commands, changelog command, and tracker done-state all come from
> `dev-workflow.yml`, so there are no `[PLACEHOLDER]` markers to hand-edit.

End-of-session ship: commit anything outstanding, push the branch, open a PR into
the base branch (merging it does NOT deploy), close out the tickets the session
completed, and leave a session handoff. Fast by default; `--full` runs the full
hygiene + test dance. See the skill for the full step sequence.
