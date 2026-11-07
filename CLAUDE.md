# CLAUDE.md

This repository is a Claude Code harness plus a self-hosted company stack: the working loop, its
skills and guards, and the apps it runs (assistant, notulen, documents, website, platform, deploy,
observability, GPU tier). The repo, the owner and the people are named in `.claude/project.json`;
nothing here hard-codes them.

## Persona

Read [`.claude/soul.md`](.claude/soul.md) for voice, hard rules, and working rhythm. Match it.

## Workflow protocol: every conversation in this repo

**On the first user message in any conversation, invoke the [`grill`](.claude/skills/grill/) skill before generating any response.** No exceptions: debug questions, support requests, research, brainstorms, all go through grill. Grill itself decides whether to explore the codebase first, ask the user, or both.

A conversation in this repo is a **task**. The flow is fixed: grill, then to-prd, then code, then [`close`](.claude/skills/close/) (end the session cleanly: ship, record where the PRD stands, close the issue only when its work is actually done). Two branches: grill's dump check sends a **brain dump**, a message that is a page of thinking rather than a task, to [`brain-dump`](.claude/skills/brain-dump/); and grill's wayfinder check sends efforts too big and fogged for one session to [`wayfinder`](.claude/skills/wayfinder/) (the effort is a PRD; its foggy pieces become investigation sub-issues, one resolved per session, until the route is clear). Otherwise grill always routes to [`to-prd`](.claude/skills/to-prd/), which synthesises the aligned plan as a PRD-style issue with no re-interview, and carves a sub-issue under the PRD when a task is independently grabbable or going ready-for-agent. First message contains `#N` or a GitHub issue URL: resume mode inside `to-prd` (re-align against the existing issue body plus the bible, amend if it drifted, then code). Long autonomous chains run under YOLO mode (`claude --dangerously-skip-permissions`); the audit-* skills and a local test run before pushing catch what permission prompts would have. Term definitions: [`CONTEXT.md`](CONTEXT.md).

**Brain dump, the first branch.** It fires whenever a message arrives as several open questions at once, visionary thinking, or a pasted conversation rather than a task. Like every skill here it is checked into the repo, so it is the same workflow for whoever is working in it. [`brain-dump`](.claude/skills/brain-dump/) sorts it into claims, questions, decisions and vision, sweeps and refutes the first two in one workflow, lands each result in its own home (a new word in `CONTEXT.md` first, a trade-off on its issue or as a proposed ADR, the thinking in the chapter it belongs to, an invariant in its bible chapter), then hands the route to `wayfinder` and creates the issues. Also `/brain-dump` by hand.

Four mechanism types make this loop work: **skills** (methodology, `/<name>`), **overlays** (per-directory `CLAUDE.md`, auto-load on file-touch), **hooks** (harness-event automation via `.claude/settings.json`), **GitHub issues** (durable backlog). One job each; mixing them creates unpredictable harness behaviour. `.claude/settings.json`, `.claude/soul.md`, the skills, the index and the hooks beside the settings are the shared harness, copied from its source repository; this repository's own hooks live in `.claude/hooks/local/`, listed in `local/hooks.json` and run by `.claude/hooks/dispatch.py`, and git runs `.claude/hooks/` (`core.hooksPath`). A change to a shared file is made at the source and copied here, or the next copy overwrites it.

### Bible chapter map (use during grill orient phase)

Topic to bible chapter ID. Pick the ones the prompt touches and read them before asking the user anything. Chapter IDs are slugs in the bible (e.g. `## architecture/system-context`); link via `docs/bible.md#architecturesystem-context`.

| Topic | Chapter ID |
|---|---|
| Big picture / system diagram | `architecture/system-context` |
| The assistant (Signal, triage, tool door) | `apps/assistant` |
| Meeting minutes (notulen) | `apps/notulen` |
| Documents (invoices, letters as PDF) | `apps/documents` |
| Website and `design/` | `apps/website` |
| Platform: Caddy, single sign-on, the vault, the cluster and its pool roles, dashkit | `infra/platform` |
| Deploy: auto-deploy, the gate, the register, the eject | `infra/deploy` |
| Observability and paging | `infra/observability` |
| GPU tier (worker image, cluster, gpu_jobs) | `infra/gpu` |
| Video calls and recording (the media node) | `infra/media` |
| Workflow: grill, plan, code, close, the mechanism stack, the board, what to run before pushing, commit style | `workflow/loop` |
| Workflow: the house module standard (tiers, layout, interface, tests, failure tiers) | `workflow/module-standard` |
| Glossary (canonical terms + `_Avoid_` aliases) | `CONTEXT.md` (repo root) |

Per-area overlays: `<area>/CLAUDE.md` auto-loads when files in its directory are touched; read the overlay closest to the file you edit. If a prompt touches 2+ areas, spawn general-purpose subagents in parallel.

**Glossary is the working surface.** Opinionated CONTEXT format: every term has `_Avoid_:` aliases. When you reach for a domain word in any output (issue title, refactor proposal, hypothesis, test name), use the canonical term, not the alias. Skills that explore the codebase obey [`.claude/skills/DOMAIN-AWARENESS.md`](.claude/skills/DOMAIN-AWARENESS.md). The `grill` skill writes glossary updates to `CONTEXT.md` inline as terms get sharpened; a decided trade-off is proposed as an ADR in one line and written only if the owner says yes.

## Agent tools

**Output: summaries, not dumps.** Every output an agent reads stays in its context and is paid for again on every later turn, so long output goes to a file and the agent reads only the part it needs. A tool here prints one summary line (counts, pass or fail, the paths it wrote) and writes the detail to a file; `--verbose` gives the full output where a tool has it. The `output_cap.py` hook (PostToolUse on Bash) does the same for any command: an output over 6,000 characters is saved whole to `$TMPDIR/output-cap/<session>/<call>.txt` (`OUTPUT_CAP_DIR` moves it), and the agent sees its first and last lines, its error and warning lines (or, for JSON, its keys and array lengths) and that file's path. Nothing is lost: read the file with Read (offset, limit), `grep` or `sed -n`. Reads you narrow yourself (`sed -n`, `head`, `tail`, `grep -c`, `wc`) and a `cat` of a rules file you must read whole (a `CLAUDE.md` overlay, `SKILL.md`, `soul.md`, `CONTEXT.md`) are left alone, and a command prefixed with `FULL_OUTPUT=1` keeps its whole output. A failing command's output cannot be replaced by a hook; send a long failing run to a file yourself (`cmd > /tmp/x.log 2>&1; tail -n 40 /tmp/x.log`).

**Never wait in the foreground.** An agent's turn that comes more than 5 minutes after its previous one re-writes its whole context to the prompt cache. So start anything that takes minutes with the Bash tool's `run_in_background` and go on with other work, or end your turn and let the completion notice wake you. To wait for a condition, use the Monitor tool. `.claude/hooks/wait_guard.py` blocks foreground sleeps over a minute, poll loops, and any long run this project lists under `wait_guard` in `.claude/project.json`. Every session keeps its prompt cache for an hour (`promptCacheTtl` and `subagentPromptCacheTtl` in `.claude/settings.json`), so a wait that cannot be avoided does not cost a re-write. Effort and quality are never cut to save tokens; only waste is.

**Code index.** The `index` MCP server (`.claude/index/server.py`, Python standard library only) answers `search_graph` (a symbol by name), `query_graph` (one Cypher query: who calls this, what imports this) and `search_code` (text, with the symbol each match sits in) from codebase-memory-mcp's index of the shared checkout. Ask it before a repo-wide grep. Its tools load up front (`"alwaysLoad": true` in `.mcp.json`, Claude Code 2.1.287 or later), so they are in the tool list from the first turn; a missing one means the server did not start. Its first question on a box installs the pinned binary (`.claude/index/pin.env`) and builds the index, a few seconds; a question after a new commit brings the index up to that commit first. Nothing stays running. A failure answers with its cause and the command that fixes it. GitHub issues of the `repo` in `.claude/project.json` are `Issue` rows with `CHILD_OF` edges (`MATCH (i:Issue) WHERE i.number = 3 RETURN i.number, i.name, i.state`; every open issue with its parent and checklist counts in one call: `MATCH (i:Issue) WHERE i.state = 'open' OPTIONAL MATCH (i)-[:CHILD_OF]->(p:Issue) RETURN i.number AS n, i.name AS t, p.number AS parent, i.open_tasks_count AS open, i.done_tasks_count AS done, i.updated AS updated ORDER BY parent, n` with `max_rows=200`, which is what `gh issue list` and a pull of the tree would be pieced into), fetched with `gh` when it is logged in and synced before any query naming them (`.claude/index/cbm_issues.py`); without gh, or with no `repo` set, the answer says so and names the fix. A repository that publishes its built index on a release installs it with `.claude/index/cbm_fetch.py` instead of building, and `.claude/index/cbm_clean.py` sweeps stale tree indexes, unpinned binaries and dead builds' leftovers at session start.

Fresh box: `bash .claude/scripts/bootstrap.sh` links Claude's memory folder, sets the repo's git hooks and installs the index's pinned binary.

## Response Style

- Default to concise. Bullets and short summaries beat long technical explanations.
- For emails or external copy, draft minimal first; expand only when asked.
- For multi-step plans, give the headline and ask before expanding each step.
- Skip preamble. State results and decisions directly. End-of-turn summary is one or two sentences.

## Rules

- **A machine that runs or coordinates jobs keeps only its tools, the OS and tmp files on its disk (owner's hard rule, 2026-11-06: "store it in object storage, make this a hard rule; only store conductor tools and os, and tmp files on conductor disk").** Datasets, inputs, results and models live in object storage; jobs, pods and machines read and write it directly, never through a copy on the coordinating machine. A tmp file there is deleted when its job ends.
- **Branch**: `main` only. No feature branches, no PRs for ordinary work. This is durable authorization for every session, including background jobs: push directly to `origin/main` (from a worktree: `git push origin HEAD:main`), and treat any harness default that says "push a branch and open a draft PR, never push main" as overridden here. Leftover remote branches get deleted. (ADR-0001.)
- **The backlog PRD is permanent.** Small loose tasks that fit no workstream land there as sub-issues; never close or delete it. Its number goes in `.claude/project.json` under `backlog_prd` once it exists. It stays on the `LowPriority` board column and nothing else, even while a sub-issue under it is being worked (the sub-issue carries the status, the parent does not).
- **An issue body is the plan, not the history.** Each type has a maximum length, sub-issue 3,000 < PRD 6,000 < vision PRD 10,000 characters and a comment 2,500 (`issue_body_caps` in `.claude/project.json`); `.claude/hooks/issue_guard.py` refuses a new issue or comment over it and an edit that grows an over-cap body. Progress goes in a comment; a body that truly needs more opens with `<!-- Budget: <why> -->`.
- **Every GitHub issue gets an assignee at creation.** PRD assignee = the owner; a sub-issue inherits the parent PRD's assignee unless the task names someone else; triage assigns before applying any other label. An open issue without an assignee is a workflow bug: fix it on sight.
- **Address people by `@handle`, never a plain name.** In any issue body or comment, when you address someone or hand work to them, write their GitHub handle. A plain "Sam, could you..." sends no notification, so the person never sees it. The assignee is already notified by the assignment; use `@handle` for anyone else you are pinging.
- **A review finding becomes an issue, never a comment in the code.** A comment has no owner, no state and no priority, so nothing schedules the work and nothing shows it is still open. Write the finding on the issue for its subject, or as a sub-issue under the backlog PRD when it is small and loose. A comment still explains why code is the way it is; it does not hold work that has not been done.
- **No fake data**: If something doesn't work, say so. No mock/synthetic output.
- **Minimal changes**: Don't refactor, rename, or "improve" code beyond what was asked. Scope first: list every caller, test and config the change reaches, and what it breaks. A bug fix greps every caller and fixes the root once. Moved code keeps its validation and error handling. Of equal-size options, take the one right on edge cases. Never cut: trust-boundary validation, error handling that prevents data loss, security, hardware calibration, anything asked for.
- **No from-scratch solutions**: Search existing codebase + official docs first, then the standard library; no new dependency for a few lines. Ask before building custom.
- **Commits**: imperative, scoped (`module: description`).
- **Verify after refactor**: After deleting >20% of a module, run the full import chain + one smoke test before committing.
- **A new `.md` file needs the owner's go-ahead (hard rule).** Ask before creating a markdown file anywhere in this repo, and take no for an answer. Every `.md` here is living: someone reads it, it has one clear purpose, and it is kept current, so the count stays minimal. What would have been a new file goes into an existing one, into a `docs/bible.md` chapter, or as a comment on the issue it belongs to; a generated page renders to a path outside the repo. **This includes ADRs**: a decision goes on the issue where it was made, and into its `docs/bible.md` chapter when it is load-bearing; an ADR is a one-line proposal ("want this as an ADR?") and gets written only after a yes. Editing an existing `.md`, ADRs included, is free. **Per-area `CLAUDE.md` overlays are the one standing exception**: a new code directory gets its overlay without asking, because the overlay is the mechanism that loads the directory's rules and a directory without one is a gap, not a document. `.claude/hooks/md_guard.py` blocks the creation routes (Write, shell redirect, `tee`, `touch`, `cp`). The guard hears a yes: when one of the owner's last twenty messages names an md or markdown file, the new file goes through. A yes given earlier is kept by adding `{"path": ..., "words": ..., "at": ...}` with the owner's words and the time to `.claude/hooks/local/md_allowed.json` (ships empty); the guard lets listed paths through, and `.claude/memory/` too. (ADR-0003.)
- **Agents: one clear role, then a handoff and a close (hard rule).** New work goes to a fresh agent with its own role brief, never a second job mid-run.
- **One function, one purpose**: Functions doing >1 thing must be split. If the docstring needs "and" between concerns, split it.
- **No single-letter variable names** in production code. Comprehensions and lambda arguments are exempt because the binding's lifetime is one line.
- **A session does not close while something needs the user or is not done; waiting on time goes to the backlog (hard rule).** Unfinished work is finished in the session, however big. A decision or action only the user can take is asked in a few plain lines and waited for. A check that only passes once days go by (a clean week, a delete after seven days, an observation window) becomes a dated sub-issue under the standing backlog PRD (`backlog_prd` in `.claude/project.json`) on `LowPriority`, and leaves the PRD's acceptance list, so the PRD closes on everything else. The `close` skill carries the steps.
- **Delete dead code**: stubs, unused exports, archived "we might need it" leftovers all go. Apply the deletion test before adding new code; deletion beats addition. New non-trivial logic (a branch, loop, parser, money or security) gets a test, in its module's test file.
- **A session that writes files works in its own worktree.** Several sessions sharing one checkout produce torn commits. Enter `.claude/worktrees/<slug>` with `EnterWorktree` before the first write, run `bash .claude/scripts/worktree-setup.sh`, and push with `git push origin HEAD:main`. A read-only session stays in the shared checkout. This bullet is the durable project authorization the `EnterWorktree` tool requires.
- **Every test has one row in the register (hard rule).** `tools/test_register/_rows.py` holds one row per test file: the module it pins, the changed paths that select it, and `proved_by`, an exact edit to a source file that must turn the test red. Never write a row by hand: `python3 -m tools.test_register --new <module> --says "<invariant>"` writes the test and its row together. The pre-commit hook and the deploy gate both refuse a tree whose tests and rows disagree, and replay the break of every row a commit touches.
- **A test and the change that makes it pass go in one commit (hard rule).** The gate judges every commit against its own tree, so a commit that adds a test its own tree fails is red for ever, and the fix in the next commit cannot rescue it.
- **Bible budget: 900 words and 8 sections per chapter.** `.claude/hooks/local/bible_guard.py` blocks an edit that grows a chapter past either without a line starting `Budget:` saying why. A chapter explains how a thing works to someone who does not know it; an inventory a reader scans (every flag, every file) belongs in the overlay.
- **Overlay budget: 500 words per `CLAUDE.md` overlay.** `.claude/hooks/local/overlay_guard.py` blocks growth past it without a `Budget:` line. An overlay says what someone must not get wrong in its directory and what will bite them; history is in git.
- **Configuration lives in three places and nowhere else**: `.claude/project.json` (repo, board, people), `config/harness.env` (settings, git-ignored, documented in `config/harness.env.example`) and the vault (the full environment with every secret, documented in `config/vault.env.example`). No id, address, name or secret is written into code or a compose file.
- **The assistant's name, zone and repo come from settings**; never write a name into `apps/assistant`.
- **`design/index.css` is the only design import.** Keep the `--color-*` and `--font-*` names: the website, the documents and dashkit all reference them.
- **A company fact printed on a document lives in `design/company.yaml`**, never in a template or in `business/`. A new or changed document in `business/` updates the register in `business/README.md` in the same commit. `business/minutes` equals `NOTULEN_TARGET_PATH`; rename both together.
- **Never send email without showing the owner the exact document and getting an explicit yes.**
- **No loose files outside the carve-out**: every directory contains only subdirectories plus an explicit carve-out list (framework-required files only: `__init__.py`, `conftest.py`, `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`, `Dockerfile*`, `.dockerignore`, `docker-compose.yml`, `compose.yml`, `Caddyfile`, `README.md`, `CLAUDE.md`, `CONTEXT.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `docs/bible.md`, `docs/diagrams/stack.html`). Anything else loose must move into a named subdir. ADR-0002. Carve-out is append-only by ADR amendment, and `docs/adr/tools/check_index.py` checks this list against ADR-0002's copy so the two cannot drift.

## Deployment

- **What a hook adds to every prompt stays small (hard rule).** Everything the hooks attach to one user prompt, all of them together, stays under 2,000 characters; today that is the soul rules in `.claude/settings.json`, about 1,400. A hook that wants to hand a session more is the wrong mechanism: put the fact behind a tool the session already has, or in the overlay or chapter it reads. Past 10,000 characters Claude Code shows the session only a 2,000-character preview of a hook's text.
- **Commit pieces of work, not fixes (hard rule).** The server checks every commit on its own and deploys one commit per run, so a commit count is a queue length. One issue, or one group of related fixes on one subject, lands as one commit with its tests; parallel fix agents hand their changes back and the group lands once. `.claude/hooks/local/pre-push` refuses a push to main while more than 15 commits wait to deploy (`PUSH_QUEUE_LIMIT`); the commit that fixes a frozen deploy carries the trailer `Unblocks-deploy: yes`. The same pre-push then refuses a push whose tip fails `test_register --check` or a test of a row the push touches, run sealed in the gate image; a red main already had is not the push's (`push_gate.py`).
- **Pushing to `main` is the deploy.** In the cluster, CronJob `deploy-cycle` (`infra/k8s/deploy/`) and the push receiver run `infra/auto-deploy/auto-deploy.sh`, one commit per cycle, from an exported tree of that commit. The gate runs as a gate Job in the image the commit's own `infra/gate-image/pin` names; a cycle builds only the stack images whose build inputs changed (the files its Dockerfile copies, `infra/auto-deploy/compose_fragments.py`), with BuildKit, and rolls each out by digest.
- **The gate fails closed.** Red (a run that happened and said no) and amber (a run that could not start or finish) both ship nothing. The commit's GitHub page (`vm/gate`, `vm/build`, `vm/boot`, `vm/deploy`) is where you see what a push did, not the Actions tab.
- **Nothing holds the queue.** A red is sorted before it is believed (`infra/auto-deploy/steps/red_triage.sh`): a test that flips, or fails on the last good tree too, is quarantined with an issue for its owner and the gate runs again without it; a red that is the commit's goes to the eject, which the shipped config arms (`EJECT_ENABLED=1`; `0` makes a red hold the queue until a person acts). Armed, it reverts the one rejected commit and hands it back on an `auto-eject/<sha>` branch with a pull request. **Never press merge on that pull request**: its first commit is the tree the gate refused. Squash the fixed branch onto `main` as one commit with `Closes #<PR>` in the message.
- **GitHub Actions never build and never test.** `.github/workflows/deploy-watchdog.yml` is the only workflow, a dead-man switch that opens one issue when the deploy cycle stops reporting; it arms itself only once `.claude/project.json` names the repository it runs in.
- **Observability and paging**: `infra/observability/` (Prometheus, Alertmanager, alert-relay, deadmen, systemd units); its own `CLAUDE.md` has the rules. Every page goes through the assistant, and straight to Signal only while the assistant is down.
- **GPU images** build by hand with `infra/gpu/build-worker.sh`; nothing builds them on push.

## Autonomy boundaries

- Don't continue into adjacent work after the requested task is done. Stop and wait.
- When a background monitor reports repeated failures, propose stopping or investigating; don't passively echo "awaiting direction".
- Never ship unverified claims (measured numbers, benchmark figures, compatibility assertions).

## Verification

- On "u sure?" or any audit/consistency check, recount from scratch; don't reuse prior assertions.
- For research/citation tasks, check current sources before drafting; do not answer from memory.
- Failures propagate. A silent `except: pass` around a write is an anti-pattern; don't add one.

## Where the rest lives

- **[`docs/bible.md`](docs/bible.md)**: single source of truth for the system (architecture, apps, platform, deploy, workflow). Read the relevant chapter, not the whole file.
- **[`docs/adr/`](docs/adr/)**: decision records.
- **Per-area `CLAUDE.md` overlays**: load automatically when you open files in their directory. Read the overlay closest to the file you're editing; deeper is more specific.
