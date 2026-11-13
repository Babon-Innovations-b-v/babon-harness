---
name: purge
description: Bring the whole repository into line with the house rules in one unattended run. Maps every module against one rulebook (the module standard, the lean-code rules in root CLAUDE.md, the codebase-design deep-module vocabulary), then sends layered agents, area by area and in parallel, to change the code until no area breaks a rule. Use when the user invokes /purge.
disable-model-invocation: true
---

# Purge

One run takes the repository from "mostly follows the rules" to "follows the rules", everywhere at once. Invoking it is the user's opt-in to a large multi-agent run: it calls the Workflow tool with [`scripts/run.workflow.js`](scripts/run.workflow.js) and does not stop between areas.

This skill is shared: it names no repository. Each repository says where its own rules and test bookkeeping live, in the `purge` key of its `.claude/project.json` (below).

## The rulebook

Every agent in the run judges code by the same three sources, in this order of precedence when they disagree:

1. **Root `CLAUDE.md` Rules**, which carry the lean-code rules (scope first, deletion beats addition, one function one purpose, no single-letter names, minimal changes) and every hard rule of this repository.
2. **The module standard**: the bible chapter `workflow/module-standard`, and its auditor's conformance checklist where it has one. A module conforms when every rule (or checklist line) passes or carries a written, sanctioned exception.
3. **The deep-module vocabulary** of the [`codebase-design`](../codebase-design/SKILL.md) skill (module, interface, depth, seam, adapter, leverage, locality, the deletion test). It decides *how* a shallow module is deepened; it never overrides 1 or 2.

Nothing outside these three is a rule. An agent that wants a new rule writes it up for the user instead of applying it.

## The repository's hooks

`.claude/project.json` key `purge`, each value a command run at the root of the run's worktree, or an instruction where the repository has no command:

| Key | What it names |
|---|---|
| `setup` | readies a fresh worktree (environment, packages) |
| `suite` | the full suite, the one judge of behaviour |
| `test_check` | the test bookkeeping agrees with the tree (red on any fault) |
| `test_debt` | lists the level debt and the gaps: extra tests per module, files over one test function or over their time |
| `test_new` | how a new test is born |
| `debt_lists` | the file and the lists in it that only shrink |
| `time_budget` | a test file's time, and the suite's |
| `modules` | what a module and a module group are |
| `duplicates` | a duplicate finder printing JSON groups, or `null` (the shared wave is skipped) |
| `extra_checks` | further checks the deploy runs, a list |

A repository without the key has no run: step 1 stops and names the missing key.

## The registers every change respects

Not rules to judge by; the bookkeeping a change keeps true, and the run fails a change that leaves one false:

- **Test bookkeeping**: a new test is born the `test_new` way, a test and its fix land in one commit, and `test_check` agrees with the tree.
- **Harness lock**: a path listed in `.claude/harness.lock` (where the repository has one) is edited like any file; its commit carries the change to the harness source.
- **Budgets**: the word budgets the repository's rules set for docs and overlays; a cut is always allowed.
- **No new `.md` file**, and no new GitHub issue except the run's own tracking comment.
- **Behaviour is kept**: conforming is refactoring. The full suite at the end of each wave judges it, and a change that alters what a caller sees is out of scope for the run.
- **One test per level, one test function a file, inside its time**: one test per module (and per module group, where the repository has groups), the full suite on top; each test file holds one test function and runs within `time_budget`. `test_debt` names the debt and the gaps; the lists in `debt_lists` only shrink.
- **Regulated modules** (the ones the module standard marks regulated) are mapped and reported, never changed by the run.

## Steps

1. **Read the hooks**: `.claude/project.json` key `purge`, every key of the table present. Completion: the object, or the run stopped naming what is missing.
2. **Load the index tools** (the code index root `CLAUDE.md` names) and confirm `query_graph` answers. Completion: one query returned rows.
3. **Find the tracking issue.** Ask the user which PRD the run reports to (`backlog_prd` in `.claude/project.json` when it is loose). Completion: one issue number.
4. **Launch the run**: `Workflow({scriptPath: ".claude/skills/purge/scripts/run.workflow.js", args: {issue: <N>, maxWaves: 6, repo: <absolute repository root>, hooks: <the purge object>}})`. Completion: a run id.
5. **Report**: when it finishes, post its summary as one comment on the tracking issue and tell the user in a few lines: areas conformed, areas left and why, the checks the retro added, the one commit pushed, and its gate verdict once it arrives. Completion: the comment URL.

## How the run is shaped

- **Map**: one agent splits the tracked tree into areas with disjoint files (modules as `modules` defines them, grouped where the index says they move together) and scores each against the rulebook, using the index for importers and hubs, `git log` for churn, and the index's `Issue` rows for open work on that area.
- **Shared wave first**: because areas are disjoint, the map first runs `duplicates`; each group inside one deploy unit becomes one high-value change in a dedicated first wave that folds the copies into one function in the group's `home` and updates every caller, the per-area leads of that wave leave those files alone, and groups that cross a deploy boundary are only reported.
- **Waves**: each wave runs one lead per broken area, as many at once as the Workflow allows. A lead plans small changes, workers make them in their own worktrees branched from the run's local branch `purge-run` and do not run tests, and reviewers try to refute each change: one against the rulebook, plus one against behaviour unless the change touches only docs. A refuted change goes back to its worker once to fix what was named, then is reviewed again. High-value changes run first (dead code out, duplicate copies folded, extra tests folded, missing tests, real depth fixes); a docstring-only or naming-only change runs only once its area has nothing more valuable left. A change that survives is merged into `purge-run` by its lead; areas that share a hub file run in different waves, so merges do not collide.
- **Two test jobs**, mapped from `test_debt` beside the rulebook breaks. **Fold**: a module's extra tests and the functions of a file on a debt list are MERGED into one test function of the answer that matters: the checks that pin the module's real behaviour survive as cases of that one test (parametrized over inputs), a check that repeats another or only reads the code's shape is deleted, and nothing is concatenated. The folded files and their debt entries go, and the survivor's break stays red. The one test fits its time: a fold that leaves a file over `time_budget` makes it faster. **Group test**: a module group with no test gets one, born the `test_new` way, driving its modules together through their seams.
- **One suite run per wave**: after a wave's merges `suite` runs once on `purge-run`. A red that was green at baseline is bisected over that wave's merges, and the merges that caused it are reverted (`git revert -m 1`).
- **Until dry**: after each wave the map is redone on `purge-run`; waves end when no area breaks a rule, or two waves in a row merge nothing, or `maxWaves` is reached.
- **Agent cap**: the Workflow tool stops a workflow at 1,000 agents, so the script counts every agent it starts; past 880 it starts no new change, lets the ones in flight finish, skips the remaining waves, and goes to the wave's suite, the retro and the deploy, with "stopped early at the agent cap" in the report.
- **Retro**: before the deploy, a retro on the run itself (the `retro` skill): every kind of break fixed in two or more places that a machine can spot becomes one automatic check, so it cannot come back; breaks that need judgement go in the report.
- **One deploy**: the run pushes once. On `purge-run` the `suite`, `test_check` and `extra_checks` run; a red is fixed on the branch, or its change is dropped from the branch, until all are green; then the branch is squashed into one commit on `origin/main` and pushed, per root `CLAUDE.md`. `purge-run` never leaves this machine.
