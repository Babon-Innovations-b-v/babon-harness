---
name: retro
description: "Conduct a retrospective on a coding session: suggest changes to the agent's environment (overlays, bible, CONTEXT.md, skills, hooks, issues) that would make future runs go better."
disable-model-invocation: true
---

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs. Every improvement lands in a home that already exists; a new `.md` file needs the owner's yes first (root `CLAUDE.md`).

Adapted from Matt Pocock's [`retro`](https://github.com/mattpocock/skills/blob/a7d038f6bf7f01b516408e95e2fb56e0b338fa6f/skills/engineering/retro/SKILL.md) (MIT, upstream commit `a7d038f6bf7f`).

## Steps

1. Call the Skill tool with `write-a-skill` for the writing style guide, and read [`.claude/soul.md`](../../soul.md) for the voice.

2. Read the primary sources for the session the user specifies. This may mean searching the session logs on this machine (`~/.claude/projects/<repo-slug>/*.jsonl`, sub-agents' included) and the full outputs `output_cap.py` saved (each capped output names its file). If the user doesn't specify a session, default to the current one.

3. Look for candidates for improvement in these categories.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** (a line in the area's `CLAUDE.md` overlay, the bible chapter map, or a `CONTEXT.md` term) make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: are there automated checks that could catch errors the agent made? Tests, linters, the hooks in `.claude/hooks/`, the project's own checks? Read what already exists first (root `CLAUDE.md` and the bible's `workflow/loop` chapter for what runs before a push, `.claude/settings.json` for the wired hooks), so a check that exists but sits unwired or silently broken is the finding, not a reinvention. Nothing in GitHub Actions builds or tests here, so the guardrail is a hook or the local test run before pushing. _Use when_ the agent made a mistake an automated check could have caught.
- **House rules**: should a rule be added, removed or clarified? Classify the violation first: a **mechanical** one (a fixed syntactic pattern, a banned API, an import shape, a file-location rule) gets a deterministic check, full stop: a hook, a test, or a project check, whichever is cheapest. Default to building the check over writing the rule. Reserve prose rules for genuine **judgement calls**, placed where they load: the overlay of the area they govern, the bible chapter they belong to, or the review pass (the audit-* skills, `/code-review`). _Use when_ a mistake got past review.
- **Root CLAUDE.md**: are there steering instructions that should move to an overlay, a bible chapter, a skill or a check instead? _Use when_ root `CLAUDE.md` or `.claude/soul.md` is particularly large.
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Long output read whole instead of through the `output_cap.py` file, waits in the foreground instead of `run_in_background` or `--detach`, a custom tool that prints far more than one summary line? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files (root `CLAUDE.md`, overlays, skills, `soul.md`) that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information: teeing logs to a file, a read-only tool for a cloud service, a summary line a tool should print. _Use when_ a crucial piece of information was not available to the agent.

4. Present these candidates to the user, in order of severity. For each, name its home: a term in `CONTEXT.md`, an invariant in its `docs/bible.md` chapter, a rule in an area's `CLAUDE.md` overlay, a method in a skill, an automation as a hook in `.claude/settings.json`, or durable work as a GitHub issue (a loose task under the backlog PRD). Apply only the ones the user picks.

## Reference

### Implementation vs Review

Remember that all work goes through two stages: implementation and review. The implementation agent has the most **context pressure**. They are responsible for exploration, writing code, and debugging failures.

The review agent has the least context pressure: it receives a diff, so no exploration needed. It often does not need to write code or debug.

This means that the review pass should be responsible for imposing coding standards, not the implementation agent.

### Homes

- Root `CLAUDE.md` and `.claude/soul.md`: pushed to the context window of every agent in this repo. Use them incredibly sparingly, usually only for **navigation pointers** and hard rules.
- Per-area `CLAUDE.md` overlays: load when a file in their directory is touched. The place for an area's rules; a new code directory gets one without asking.
- `docs/bible.md`: the single source of truth for the system; a load-bearing invariant goes into its chapter.
- `CONTEXT.md`: the glossary; a sharpened term goes here, with its `_Avoid_:` aliases.
- Skills: use them for methods, since their description goes into the agent's context window, or for user-invoked commands. Follow the `write-a-skill` skill.
- Hooks (`.claude/hooks/`, wired in `.claude/settings.json`): for anything that must happen every time.
- GitHub issues: for work that outlives the session.
