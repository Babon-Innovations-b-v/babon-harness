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

- **deploy gate**: the step of the deploy cycle in the cluster that runs the tests a commit can reach, against that commit's own tree, as gate Jobs in its gate image, before anything is rolled out. Only a green verdict ships. _Avoid_: CI, pipeline, checks.
- **verdict**: what one gate run says about one commit: green (ship it), red (a run that happened and said no), or amber (a run that could not start or finish; retried, never cached, never ejected). _Avoid_: result, status, outcome.
- **eject**: the gate's answer to a red commit when `EJECT_ENABLED=1`: revert it on `main` and hand the work back, byte for byte, on a branch and pull request for its author to fix and land again as one commit. _Avoid_: rollback, auto-revert.
- **test register**: `tools/test_register`, one row per test file naming the module it pins, the changes that select it, and the break that proves it can fail. _Avoid_: test list, test manifest.
- **module group**: a folder under which two or more modules sit, at any depth, that is not a layer; worked out from the tree (`tools/test_register/_groups.py`), never typed. A module with two or more modules under it is a group as well: its own code stays the module, and a test of how the modules under it fit counts as `<dir> (group)`. Each module and each module group has exactly one test. _Avoid_: package family, subsystem, component.
- **quarantined test**: a test file the deploy gate took out because it judged a red the test's fault (it fails on the last good tree too, or the same commit passes it on a re-run): a `quarantined=` line on its register row that only the gate writes, an issue for the row's owner, and a note on the commit's gate status. No time limit; the owner deletes the line in the commit that fixes the test, and every other test stays in the gate and fails closed. _Avoid_: skipped, xfail, muted, disabled test.
- **synthetic ground truth**: the made-up input and the answer known in advance that a module's one test function checks its purpose against: built inside the test, never read from a live machine, a clock, the network or production data, so the test gives the same verdict anywhere. Cases of it may be parametrized, never pasted in as a second function. _Avoid_: fixture (a pytest mechanism, not the answer), mock data, sample data, golden file.
- **gate image**: the one container image a gate test run uses, built from `infra/gate-image/Dockerfile` and named by digest in `infra/gate-image/pin`; the commit hook runs a new or changed test in it with the network off and a fake clock. _Avoid_: CI image, test container, runner image.
- **break**: the exact edit in a register row that must turn its test red; replayed by the pre-commit hook for every row a commit touches. _Avoid_: mutation, sabotage.
- **marker**: the ◈ link at the end of a piece of bible text that claims one box on one drawn page; `linkmap.py` checks every box has exactly one. _Avoid_: anchor, diagram link.
- **vault**: the one Scaleway Secret Manager secret holding the full environment, every change a new version, read into the cluster as Secrets by the External Secrets operator. _Avoid_: secrets file, env file, keystore, env cache (the VM-era copy pulled to a server).
- **pool role**: what a node pool is for (`system`, `gate`, `media`, `gpu`), set as a node label every pool of the role carries; a pod selects the role, never a pool by name, so it can land on any of the role's pools. _Avoid_: node group, pool type, workload class.
- **stock fallback**: an empty pool of a pool role in another machine type or zone, tried by the autoscaler only after the role's preferred pool could not get a node because the provider had none in stock. _Avoid_: backup pool, spare pool, failover pool.
- **cluster**: the one Kubernetes cluster the whole stack runs in, created or adopted from `config/harness.env` by `infra/cluster/`: its services as Deployments, the deploy loop as a CronJob and the gate as Jobs. _Avoid_: server, VM, host, box (the single-server era it replaced).
- **warm gate node**: a node of the `gate` pool role kept up during working hours (`POOL_GATE_WARM`, `WORKING_DAYS`, `WORKING_HOURS`), so a gate Job in working hours does not wait for a node to boot. _Avoid_: standby node, hot node, reserved node.
- **media node**: the one node of the `media` pool role, holding the reserved public address, where video calls and their recording run. _Avoid_: TURN server, call server, media VM.
- **lane**: the verifying lane, `infra/auto-deploy/commit_gate/`, run by CronJob `commit-gate`: the verifier that judges commits ahead of the deploy cycle and writes a verdict per commit the cycle can trust. _Avoid_: pre-gate, CI, commit-gate timer.
- **trusted head**: the newest commit past the bookmark up to which every commit has its own verdict from the lane (a replayed green, a batch green, no reachable test, or a red a later covered commit reverts); the cycle ships it without running pytest again. _Avoid_: verified head, green tip.
- **batch**: a run of commits the lane verifies once, on the newest one's tree, and splits only while red. _Avoid_: bundle, range run.
- **assistant**: the company's assistant on Signal, built on an OpenClaw gateway plus this repository's tools, answering from the calendar, the repository and the server's own health. Ships empty and is wired to the owner's own number. _Avoid_: bot, agent, chatbot.
- **gateway**: the upstream OpenClaw process that owns the chat channel, the conversations and the sessions. It reaches this repository's tools only through the door. _Avoid_: bot server, chat backend.
- **door**: the MCP server in `apps/assistant` that serves the assistant's tools to the gateway; the only way the gateway reaches anything of ours. _Avoid_: tool server, API, bridge.
- **page**: a message the assistant sends a person unasked because something needs them. _Avoid_: alert (an alert is what Prometheus fires; a page is what reaches a phone), notification.
- **page hold**: a page that is not urgent enough to send now, kept and sent later or merged into the next one rather than dropped. _Avoid_: queue, snooze, delay.
- **quiet hours**: the hours in the owner's timezone when only urgent pages go out; everything else waits in a page hold. _Avoid_: do not disturb, mute, night mode.
