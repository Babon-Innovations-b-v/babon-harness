# babon-harness: Domain Context

Canonical vocabulary for this codebase: the terms that mean something specific here, each with
the aliases to avoid (`_Avoid_:`). This is the working surface: [`grill`](.claude/skills/grill/)
challenges new terms against it and writes new ones here inline. Glossary only: no implementation
detail, no architecture prose. That lives in [`docs/bible.md`](docs/bible.md).

Format rules: [`.claude/skills/grill/CONTEXT-FORMAT.md`](.claude/skills/grill/CONTEXT-FORMAT.md).

## Language

- **soul**: the checked-in voice spec [`.claude/soul.md`](.claude/soul.md): the rules that fix how the assistant, and therefore most of this project's text, sounds. Every correction to the voice lands here as a rule, and the `UserPromptSubmit` hook in `.claude/settings.json` replays the rules verbatim on every prompt. Treated as a variable to pin down, not a preference. _Avoid_: persona file, style guide, tone guide, system prompt.
- **bible**: [`docs/bible.md`](docs/bible.md), one file, chaptered. The single source of truth for how the system works. _Avoid_: docs, wiki, handbook.
- **PRD**: a GitHub epic issue: one coherent module or workstream, with goal, scope, tasks and a verifiable definition of done. The unit of work and the planning surface. _Avoid_: epic (same thing, one name only), ticket, story.
- **vision PRD**: a PRD that also carries the `vision` label: a long-term direction rather than operational work. It is the largest issue type, so its body may run longest: a sub-issue is capped below a PRD and a PRD below a vision PRD (`issue_body_caps` in `.claude/project.json`, defaults in `.claude/hooks/issue_guard.py`). _Avoid_: vision issue, vision epic, roadmap PRD.
- **sub-issue**: a task carved out from under a PRD, natively linked so the board nests it. Only for work that is independently grabbable or going `ready-for-agent`; everything else stays a checklist line. _Avoid_: child ticket, subtask.
- **overseer**: the one session that coordinates the others running side by side: it hands out work, tracks what each is doing, and is who a session reports to when it ends. Found by name among the live sessions; it writes no code of its own. _Avoid_: hive, coordinator, lead, main session (main is the branch).
- **overlay**: a per-directory `CLAUDE.md` that the harness auto-loads when a file in that directory is touched. _Avoid_: local rules, sub-config.

## Architecture vocabulary (Pocock's laws)

The core depth/seam vocabulary used by `improve-codebase-architecture`, `tdd`, `diagnose`, `to-prd`. Full definitions: [`.claude/skills/codebase-design/SKILL.md`](.claude/skills/codebase-design/SKILL.md).

- **module**: anything with an interface and an implementation. _Avoid_: unit, component, service.
- **interface**: everything a caller must know: types, invariants, ordering, errors, config, perf. _Avoid_: API, signature.
- **implementation**: code inside the module. _Avoid_: internals, body.
- **depth**: leverage at the interface. _Avoid_: thickness, size.
- **deep**: small interface, lots of behaviour behind it.
- **shallow**: interface nearly as complex as the implementation. _Avoid_: thin, anaemic.
- **seam**: where an interface lives. _Avoid_: boundary.
- **adapter**: concrete thing satisfying an interface at a seam. _Avoid_: impl, plugin.
- **port**: interface defined for cross-seam dependencies.
- **leverage**: what callers get from depth. _Avoid_: reuse.
- **locality**: what maintainers get from depth. _Avoid_: cohesion.
- **deletion test**: imagine deleting the module: complexity vanishes → kill; reappears across N callers → deepen.
- **wide layer**: `ls` >12 entries (ignoring build output, caches, `node_modules`, `.venv`, `.git`). Missing boundary. _Avoid_: bloated, junk drawer.
- **split-brain**: same domain in 2+ top-level dirs sharing a name. Fix: pick one home or rename. _Avoid_: scattered, duplicated.
- **deepen**: collapse a wide layer behind ≤7 public symbols; internal files private (`_prefix`).
- **group**: sort a flat pile into named subdirs; no interface change.
- **no-loose-files rule**: every dir = subdirs only, plus a framework carve-out list. ADR-0002 holds the why and the amendment procedure; the authoritative carve-out list is in root `CLAUDE.md`. _Avoid_: top-layer-cleanup, no-floaters.

## Project vocabulary

- **deploy gate**: the step on the server that runs the tests a commit can reach, against that commit's own tree, before anything is swapped in. Only a green verdict ships. _Avoid_: CI, pipeline, checks.
- **verdict**: what one gate run says about one commit: green (ship it), red (a run that happened and said no), or amber (a run that could not start or finish; retried, never cached, never ejected). _Avoid_: result, status, outcome.
- **eject**: the gate's answer to a red commit when `EJECT_ENABLED=1`: revert it on `main` and hand the work back, byte for byte, on a branch and pull request for its author to fix and land again as one commit. _Avoid_: rollback, auto-revert.
- **test register**: `tools/test_register`, one row per test file naming the module it pins, the changes that select it, and the break that proves it can fail. _Avoid_: test list, test manifest.
- **break**: the exact edit in a register row that must turn its test red; replayed by the pre-commit hook for every row a commit touches. _Avoid_: mutation, sabotage.
- **marker**: the ◈ link at the end of a piece of bible text that claims one box on one drawn page; `linkmap.py` checks every box has exactly one. _Avoid_: anchor, diagram link.
- **vault**: the one Scaleway Secret Manager secret holding the full environment, every change a new version, pulled to the server each deploy cycle. _Avoid_: secrets file, env file, keystore.
- **assistant**: the company's assistant on Signal, built on an OpenClaw gateway plus this repository's tools, answering from the calendar, the repository and the server's own health. Ships empty and is wired to the owner's own number. _Avoid_: bot, agent, chatbot.
- **gateway**: the upstream OpenClaw process that owns the chat channel, the conversations and the sessions. It reaches this repository's tools only through the door. _Avoid_: bot server, chat backend.
- **door**: the MCP server in `apps/assistant` that serves the assistant's tools to the gateway; the only way the gateway reaches anything of ours. _Avoid_: tool server, API, bridge.
- **page**: a message the assistant sends a person unasked because something needs them. _Avoid_: alert (an alert is what Prometheus fires; a page is what reaches a phone), notification.
- **page hold**: a page that is not urgent enough to send now, kept and sent later or merged into the next one rather than dropped. _Avoid_: queue, snooze, delay.
- **quiet hours**: the hours in the owner's timezone when only urgent pages go out; everything else waits in a page hold. _Avoid_: do not disturb, mute, night mode.
