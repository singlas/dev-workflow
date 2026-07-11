# Skill: release — the base→prod promotion that DEPLOYS

> **This is now a real, installable plugin skill:
> [`skills/release/SKILL.md`](../../skills/release/SKILL.md).**
> Install it via the `dev-workflow` plugin, or copy `skills/release/` into your
> repo's `.claude/skills/`. It is config-driven — the base/prod branches, deploy
> trigger, version file/scheme, changelog, and announce channel all come from
> `dev-workflow.yml`, so there are no `[PLACEHOLDER]` markers to hand-edit.

The deliberate base→prod promotion that deploys: absorb hotfixes, run the test
gate, bump the version, regenerate the changelog, tag, and open the base→prod PR —
then STOP so the human merges (merging is what deploys). **Refuses to run unless
`repo.prod_branch` and `deploy.trigger` are configured** — no guessing on anything
that deploys. See the skill for the full step sequence.
