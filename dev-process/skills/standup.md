# Skill: standup — session opener

> Claude Code: save as `.claude/skills/standup/SKILL.md` with a `description:`
> frontmatter listing triggers ("standup", "what should I work on", "what's next").
> Placeholders to adapt: `[TRACKER]` (we use Linear via its MCP), label names.

Run at the START of a dev session to orient on the board and decide what to work on.
It is **orientation, not action** — don't start coding, don't move ticket states, don't
open worktrees. Surface, recommend, then let the human pick.

## 1. Fetch the live board (always, first)

Pull the current open issues from [TRACKER] — never reason from memory or a stale
snapshot. Group: In Progress / Todo by priority / blocked-or-gated.

## 2. Orient — where did I leave off?

- **In Progress issues are the strongest start candidates** — finishing a started
  thread beats opening a new front. Lead the brief with these.
- Skim recent commits for in-flight context: `git log --oneline -15`.

## 3. Hygiene line (one line, every standup)

Check and report in a single line — these rot silently otherwise:
- unpushed commits on the trunk (`git rev-list --count origin/dev..dev`),
- agent PRs awaiting human review (`gh pr list --base dev --state open`), with age,
- dead worktrees (`scripts/worktree-reset.sh --gc` candidates).

## 4. Surface the broad themes

A compact read of the board's *shape*, not a list dump: counts by project/label, which
milestone has motion, and any decision-labelled ticket blocking downstream work.

## 5. Recommend starting points

Pick **2-4** issues, each with a one-line *why*. Order:
1. **Resume** — In Progress work.
2. **Unblocks the current gate/milestone.**
3. **High priority + unblocked.**

Exclude gated/decision-labelled work. Offer a mix of effort (one quick win, one meatier
task). Read the ticket body before recommending it — the *why* must be real.

## Output — a tight brief, scannable in ten seconds

- **Left off:** resume candidates + one-liner of in-flight context.
- **Hygiene:** the one-liner from step 3.
- **Start here:** 2-4 issues as `ID — title · why`.
- **Board shape:** 2-3 lines.
- Close with: *want me to scope one, or move it to In Progress and start?*

## Never
- Start coding or mutate the board — this skill only orients.
- Recommend gated/decision-labelled work as "start now".
