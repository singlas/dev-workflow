# Skill: standup — session opener

> **This is now a real, installable plugin skill:
> [`skills/standup/SKILL.md`](../../skills/standup/SKILL.md).**
> Install it via the `dev-workflow` plugin, or copy `skills/standup/` into your
> repo's `.claude/skills/`. It is config-driven — everything repo-specific (board
> snapshot command + views, tracker team/roles) comes from `dev-workflow.yml`, so
> there are no `[PLACEHOLDER]` markers to hand-edit.

Session opener: regenerate the live board, orient on where you left off, surface
the board's shape, and hand back 2-4 recommended starting points each with a
one-line why. Read-only — it never starts work or moves ticket states. See the
skill for the full step sequence.
