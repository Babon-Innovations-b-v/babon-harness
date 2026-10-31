---
name: to-prd
description: Turn the aligned grill output into a readable, goal-first PRD (a GitHub epic issue) on the repo named in .claude/project.json, and carve a sub-issue under it when a task is independently grabbable or going ready-for-agent. Synthesises from conversation context; does not re-interview. Resume an existing PRD if the first message had #N or a GitHub URL. Always the next step after grill.
---

# To PRD

Produce ONE readable, goal-first **PRD epic** as a GitHub issue. Do NOT re-interview; grill already did that. Synthesis and publish.

**A PRD is an epic; they are the same thing.** Every `to-prd` run produces exactly one PRD epic: one parent issue with the `PRD` label. Never a loose, standalone issue that you later "promote" to an epic. Even the smallest plan becomes a PRD epic; the tasks live under it (checklist lines, or sub-issues via section 6), not as loose issues.

The PRD is the **planning surface and the unit of work**: someone who was not in the session scans it in 30 seconds (goal, scope, status), and the implementation detail sits in a collapsible Technical block. One module = one PRD epic; granular work lives *under it* (a checklist, or a sub-issue only when independently grabbable or `ready-for-agent`). Planning always lands here as a concrete PRD plus tasks, never as loose prose.

**Small, isolated change → backlog, no PRD of its own.** If the work touches one scoped part and is done in one session (a refactor, a rename, a loose fix, a config change), it is a **sub-issue**, not a PRD epic. It nests under the standing backlog PRD, whose number is `backlog_prd` in `.claude/project.json`; if the project uses areas, a small task in another area nests under that area's workstream PRD instead. A PRD of its own is for a module or workstream that carries multiple tasks and progress over time. In doubt: is this "an epic with tasks under it" or "one task"? For one task, carve a sub-issue (section 6) and skip the PRD epic. The size of the diff does not make it a PRD; scope and lifetime do.

**Two fields are mandatory; without both you do not publish the PRD:**

1. **Definition of done** (`## Acceptance (done when)`): a clear, verifiable list that says when the PRD is done. No vague "works well"; every point is checkable (a command, a file, a decision made).
2. **Owner** (`## Owner · Horizon`): one named person, no "?" and no team. The owner is responsible for getting the PRD done. Priority is not a field: it lives as board status (the `LowPriority` column), not in the body.

## Writing style (soul.md, mandatory)

A PRD is read by people who were not in the session. Write every PRD per [`.claude/soul.md`](../../soul.md):

- Plain words plus the terms from `CONTEXT.md`. No invented jargon, no marketing tone; write for someone outside the project.
- Length follows the content. Write the shortest version that is fully clear, then stop.
- No em dashes. Use commas, colons, semicolons.
- State the goal and the decision directly. No preamble, no noise.
- Everything reader-facing (Goal, Scope, Status, Tasks, Acceptance) in English (root `CLAUDE.md`). Code names, paths, endpoints and labels stay unchanged.

## Process

Throughout: `REPO` is the `repo` field in `.claude/project.json`. Read it once, use it in every `gh` call.

### 1. Resume mode (if applicable)

First message had `#N` or a GitHub issue URL → `gh issue view <N> --repo $REPO --json title,body,state --comments`, load the body, re-align against the grill output, amend with `gh issue edit` only if it drifted. Do NOT create a new issue. Before the first line of code, set the board Status: `python3 .claude/scripts/board-status.py <N> "In Progress"` (work starts now; do not leave this to [`close`](../close/SKILL.md)). Then skip to the code phase.

### 2. Explore (if you haven't already)

Follow [`.claude/skills/DOMAIN-AWARENESS.md`](../DOMAIN-AWARENESS.md): read `CONTEXT.md`, the relevant bible chapter and the ADRs first. Use `CONTEXT.md` vocabulary throughout the PRD.

### 3. Pick the module and shape

One PRD = one coherent module or workstream. Does the work span multiple modules? Then it is multiple PRDs, or you are at the wrong altitude: re-grill.

For code work, sketch the **deep modules** and the **test seams** (vocabulary: the [`codebase-design`](../codebase-design/SKILL.md) skill). Test at the highest seam, the public interface and not the internals. This belongs in the **Technical block**, not in the readable header. For work that is not code, skip the Technical block entirely.

Check with the user that the module boundary, and for code the test seams, is right.

### 4. Publish

Before you publish, check the two mandatory fields: a clear **Acceptance** list and a **named Owner**. If one is missing, fill it in or ask; do not publish without.

**First: loose, or under a parent PRD?** Does this work belong under an existing parent PRD (a follow-up, or a larger effort grill named)? Then it is **not a loose top-level PRD**: skip the `PRD` label and nest it as a native sub-issue, see 4b. Only a standalone, top-level effort gets the `PRD` label. In doubt: if it has a clear parent PRD, you nest.

**A new PRD is a new root, so check the roots first.** The backlog is a tree: PRD-labelled roots on top, their children carrying `bug`/`enhancement`, three layers at most, and one root per subject. A session that reads its own prompt as a new workstream opens a second root beside one that is already open, so before you publish:

```bash
gh issue list --repo $REPO --label PRD --state open --limit 60
```

Read that list against the subject you are about to open, remembering that a root's subject also lives in its children and its title may use another word for it. If a root covers this subject, nest under it instead (4b). If none does, say so in the body:

```markdown
## Root check
Checked the open roots; #<N> (<its subject>) is the nearest and this is separate because <one line>. No open root covers <subject>.
```

`.claude/hooks/issue_guard.py` enforces both halves at creation: a `PRD` label on an issue whose body names a `## Parent` is refused, and a PRD without a `## Root check` section, or one whose subject overlaps an open root the section does not name, is refused with that root's number.

`gh issue create --repo $REPO`. Title under 70 characters, imperative, no emoji. Labels: `PRD`, plus the area label when the project uses areas (`area_label_prefix` and `areas` in `.claude/project.json`, so `<prefix><area>`), and nothing else: no `bug`/`enhancement` (a category belongs on sub-issues) and no triage labels (`needs-triage`/`ready-for-*`; triage routes the grabbable pieces, not the epic itself). Add the vision label (whichever of `vision` or `visie` `gh label list` shows) if this is a long-term vision PRD rather than operational work, which splits the roadmap into two views. Print the URL.

**Assignee = Owner.** Set the GitHub assignee right away, so the board's Owner column is right and not just the Owner line in the body. Map the name to the login with the `people` map in `.claude/project.json` and pass `--assignee <login>`. If the owner is not in that map, or the login is not assignable, do not publish: ask the user for the right login and add it to the map. An issue without an assignee does not exist (CLAUDE.md rule).

Then put it on the board:

```bash
python3 .claude/scripts/board-status.py <N> "Not started"
```

That adds the issue to the board when the auto-add workflow is off, and sets the column either way. If the board also carries an area field, set it to the same area as the label, so the board's swimlanes match (field and option ids from `gh project field-list <number> --owner <owner> --format json`).

### Horizon (planning, not a deadline)

Every PRD gets a **horizon** at creation: roughly where it lands. Not binding; you move it later. Three buckets, mapped to quarters from today:

- **now** = the current quarter · **next** = +1 quarter · **later** = +2 quarters.

Work the quarter out from today's date (Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec; roll the year over at Q4 → Q1), so "now" rolls along by itself. Write the bucket on the Owner line. The board also carries **Roadmap start** and **Roadmap end** date fields (created by `setup-github.py`) if you want the roadmap view; set them from the board UI, or with `gh project item-edit --project-id <id> --id <item> --field-id <field> --date <YYYY-MM-DD>` using the ids from `gh project field-list <number> --owner <owner> --format json`.

```markdown
## Root check
Which open PRD roots you looked at, and why this subject is not one of them. Mandatory on every PRD; the hook refuses a PRD without it.

## Goal
Why this exists and what it delivers, 2-3 sentences, plain language, readable by someone who was not in the session.

## Scope
What is in scope here, and explicitly what is not.

## Status
One line: where we are now.

## Tasks
- [ ] Task; small → a checkbox here; independently grabbable or agent-ready → a link to a sub-issue (section 6)
- [ ] ...

## Acceptance (done when)
- [ ] Verifiable criterion
- [ ] Verifiable criterion

Mandatory. This is the definition of done; [`close`](../close/SKILL.md) reads this list to decide whether the PRD can close. No vague criteria.

## Owner · Horizon
<named person, mandatory> · <now | next | later>

When the project uses areas, the area goes between them: `## Owner · Area · Horizon`.

---
<details><summary><b>Technical</b> (code PRDs only)</summary>

**Implementation:** modules to build or change, interfaces, schema changes, contracts. No file paths or code snippets (they go stale). Exception: a decision snippet from a prototype (a state machine, a reducer, a schema, a type shape).

**Testing:** what is tested, the prior art in the codebase, and what a good test is here (external behaviour, not implementation). Tests sit with the module they test, per the bible's `workflow/module-standard`.
</details>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### 4b. Parent PRD (nest, not loose)

Does this work belong under an existing parent PRD? Then link it as a **native sub-issue** under the parent (same mechanism as section 6). A text reference in the body is not enough: only the real link nests it on the board and fills the "Sub-issues progress" bar; otherwise it floats as a loose card. A `PRD` label underneath would make a third layer the board does not show, so a nested child carries `enhancement`/`bug`, not `PRD`.

**Pick the parent, don't guess it.** Two mistakes are common: the wrong parent number, and body text without the real link. Prevent both:

1. **Search the candidates** instead of picking from memory: `gh issue list --repo $REPO --label PRD --state open --limit 60`. Match on workstream (what does this work substantively belong under), not on the first PRD grill mentioned.
2. **Confirm the number with the user** before you nest: one line, "parent = #N (title), because …". This is the exception to "no re-interviewing": one cheap check that stops a recurring mistake. In doubt, or with several candidates, always ask.

```bash
OWNER=${REPO%/*}; NAME=${REPO#*/}
DBID=$(gh api graphql -f query='query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){issue(number:$i){databaseId}}}' \
  -F o="$OWNER" -F n="$NAME" -F i=<new-issue> --jq '.data.repository.issue.databaseId')
gh api --method POST repos/$REPO/issues/<parent-PRD>/sub_issues -F sub_issue_id=$DBID
```

Put a `## Parent` section at the top of the body with `#<parent-PRD>`.

**Verify that the link took** (the body text and the real link must not diverge):

```bash
gh api graphql -f query='query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){issue(number:$i){parent{number}}}}' \
  -F o="$OWNER" -F n="$NAME" -F i=<new-issue> --jq '.data.repository.issue.parent.number'
```

This must return exactly the parent number from `## Parent`. If it is `null` or a different number, the sub-issue POST did not succeed or you pointed at the wrong parent: fix it now, do not let it float as a loose card.

### 5. Track under the PRD

If you continue building in the same session (the normal flow), put the PRD on `In Progress` right away: `python3 .claude/scripts/board-status.py <N> "In Progress"`. Do not wait for [`close`](../close/SKILL.md); an issue being worked on is never on `Not started`.

Development is tracked IN this PRD: the **Tasks** checklist, comments for progress, and sub-issues **only** for independently grabbable or `ready-for-agent` pieces. Do not explode into child issues up front. If a task really breaks out, carve it into a sub-issue (section 6).

Triage labels (`needs-triage` → `ready-for-agent`/`ready-for-human`, see [`triage`](../triage/SKILL.md)) route who picks a piece up.

### 6. Carve a sub-issue (only independently grabbable or ready-for-agent)

By default a task lives as a checklist line in the PRD. Only carve it into its own sub-issue when it deserves its own card:

- **independently grabbable**: one person or agent picks it up alone and also finishes it, or
- **`ready-for-agent`**: it needs its own agent brief (see [`../triage/AGENT-BRIEF.md`](../triage/AGENT-BRIEF.md)).

Everything else stays a checklist line. Prefer few sub-issues over many; the board shows readable PRD epics, not a sea of loose tasks. Present what you would carve (title · AFK/HITL · blocked-by) and let the user confirm. HITL = a human is needed (design, judgment, outside access); AFK = it can land without one.

Per approved task, `gh issue create`, link it as a **native sub-issue** under the PRD (same POST and verification as 4b), and:

- Labels: a category (`bug`/`enhancement`), plus the area label when the project uses areas. No `PRD`. Lower priority is the `LowPriority` board column, never a label.
- **Assignee inherits the parent PRD, all owners**: `gh issue view <PRD> --repo $REPO --json assignees --jq '.assignees[].login'`, each passed as `--assignee <login>`. If the task names a different owner, use that one. If the parent has no assignee, stop and fix the PRD first. Never an issue without an assignee.
- **AFK, no human needed** → label `ready-for-agent` plus the agent brief. **Needs a human** → `ready-for-human`.
- Put it on the board: `python3 .claude/scripts/board-status.py <N> "Not started"`.
- Update the PRD **Tasks** line to link the sub-issue; do not change the parent otherwise.

```markdown
## Parent
#<parent-PRD-issue-number>

## Goal
One line: what this piece delivers within the PRD.

## What to build
The behaviour end to end, not layer by layer. No file paths or snippets (they go stale). Exception: a decision snippet from a prototype.

## Acceptance
- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by
- #<issue-number>  (or "None, can start now")

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
