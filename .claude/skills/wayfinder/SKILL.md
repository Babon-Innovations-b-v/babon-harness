---
name: wayfinder
description: Plan an effort too big and too foggy for one session as a PRD whose route is unknown, breaking the fog into investigation sub-issues resolved one per session until the way to the goal is clear. Use when grill's wayfinder check fires, the user says "wayfinder", or an idea arrives too big and unclear for a normal PRD.
---

# Wayfinder

A loose idea has arrived, too big for one session, and wrapped in fog: the way from here to the **destination** is not visible yet. Wayfinding is finding that way, not charging at the destination.

A wayfinder effort uses this repo's own units, nothing new: it **is a PRD**, and its steps **are sub-issues** of that PRD. No separate "map" object, no "ticket". The PRD is the durable plan; each foggy piece becomes an investigation sub-issue; you resolve one per session until the route is clear. When it is clear, the PRD proceeds like any other (its remaining sub-issues become normal build work).

The **destination** is named first and shapes every sub-issue: a spec to hand off, a decision to lock, or a change made in place.

## Plan, don't do

Each investigation sub-issue resolves a decision; the effort is charted when nothing is left to decide before someone goes and builds. The pull to just do the work is the signal you have reached the edge of the fog: stop and let normal build sub-issues take over. Produce decisions here, not deliverables, unless the PRD's Notes say otherwise.

## The PRD body

The PRD is an **index**, not a store: a decision lives in exactly one place, its sub-issue; the PRD gists and links. Open sub-issues are found by query, not listed in the body. On top of a normal PRD, a wayfinder PRD carries:

```markdown
## Destination
<what reaching the end looks like: the spec, decision, or change. One or two lines; every session orients to it first.>

## Decisions so far
- [<closed sub-issue title>](link), <one-line gist of the answer>

## Not yet sharp
<!-- the fog: in-scope questions not yet sharp enough to be a sub-issue -->

## Out of scope
<!-- work ruled beyond the destination; never graduates in -->
```

Keep the normal PRD fields too (Root check, Owner, horizon, and the area when the project uses areas). Refer to the PRD and every sub-issue by its title with the number inside the link, never a bare `#42` wall.

## Investigation sub-issues

Each is a **sub-issue** of the PRD (same mechanics as `to-prd` section 6), inheriting the PRD's assignee unless it names someone else. Body is one `## Question` section: the decision or investigation it resolves, sized to one session. The answer is not in the body; it lands as a resolution comment on close.

Each carries one `wayfinder:<type>` label:

- **research** (AFK): read docs, third-party APIs, or local records to surface a fact a decision waits on. Use when the knowledge needed lives outside the current working directory. **Resolved by a subagent**, not in the session: spawn a general-purpose subagent per research sub-issue, let them run in parallel, and link each one's markdown summary as an asset on its sub-issue.
- **prototype** (HITL): raise fidelity with a cheap, rough, concrete artifact to react to, an outline, a rough take, a stub, or UI/logic code via the `prototype` skill; link it.
- **grilling** (HITL, the default): interview via the `grill` skill's session discipline, one question at a time.
- **task** (HITL or AFK): manual work that must happen before a decision can be made (provision access, move data). The one type that *does*; it earns its place by unblocking a decision, and its resolution records the facts later sub-issues depend on.

HITL means worked *with* a human who speaks for themselves; never answer the human's side yourself.

**Claim**: every issue here is assigned at creation, so the assignee cannot be the claim. Add the `wayfinder:claimed` label **before any work**; concurrent sessions skip claimed sub-issues. Closing resolves the claim; abandoning removes the label.

**Blocking**: use GitHub's native blocked-by so it renders in the tracker: `gh api -X POST repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by -F issue_id=<blocker id>` (repo from `.claude/project.json`); read via GraphQL `blockedBy` / `blocking`. Takeable-now = the open, unblocked, unclaimed sub-issues. Create the `wayfinder:*` labels once with `gh label create` if missing.

## Fog

The PRD is deliberately incomplete: don't write a sub-issue for what you can't yet see. **Not yet sharp** holds the dim view, the questions you sense coming but can't pin down because they hang on open sub-issues. Resolving one clears fog ahead of it, turning whatever is now sharp into fresh sub-issues.

**Fog or sub-issue?** Can you state the question precisely now (not: answer it now)? Sharp question → sub-issue, even if blocked. Not yet phrasable → fog; don't pre-slice it.

**Out of scope** is different: work consciously ruled beyond the destination; it never graduates in. A sub-issue exposed as past the destination gets **closed**, with one line in Out of scope (gist + why, linking it), and stays out of Decisions.

## Invocation

Two modes. Either way, **never resolve more than one sub-issue per session, with one exception: research sub-issues.** Those are resolved by subagents and can be burned down in parallel, any number at a time, because they surface facts rather than make decisions. Decisions stay one per session.

**Every issue you create here (the PRD and every sub-issue) gets an assignee and a category label**, and lands on the board. After each `gh issue create`, set its column with `python3 .claude/scripts/board-status.py <N> "Not started"`, which also adds it to the board when the auto-add workflow is off. If the project uses areas, add the area label too (`<area_label_prefix><area>`, both in `.claude/project.json`), and set the board's area field to match when it has one.

### Chart the PRD (invoked with a loose idea, or an existing PRD number)

1. **Name the destination** via a grilling session; the destination fixes the scope, so it is settled first. Everything on the PRD is the user's decision, put to them one question at a time, never guessed and back-filled.
2. **Find the takeable-now steps**: grill again, breadth-first across the whole space, surfacing the open decisions and the first steps takeable now. If no fog surfaces (the whole journey fits one session), you don't need wayfinder: stop, say so, route back to normal grill.
3. **Write the PRD** (or amend the existing one): Destination filled, Decisions empty, fog sketched into Not yet sharp. If a PRD already exists for this (e.g. grill routed here with a number), amend it in place rather than making a new one.
4. **Lay the whole thing back to the user for a yes** before creating a single sub-issue. On the yes, create the specifiable sub-issues, then wire blocking in a second pass (issues need numbers before they can reference each other).
5. **Fire the research subagents.** For every `wayfinder:research` sub-issue just created, spawn a subagent to resolve it, all in parallel. Each writes its findings to a markdown file, links it from its sub-issue, and the sub-issue closes with a resolution comment like any other. This is the one thing charting resolves rather than only planning, because facts do not need a session of their own.
6. Stop; charting is otherwise one session's work.

### Work the PRD (invoked with a PRD number, one sub-issue optional)

1. Load the PRD body only, not every sub-issue.
2. Choose the sub-issue: the user's, or the first takeable-now one. **Claim it** before any work.
3. Resolve it, reading related or closed sub-issue bodies on demand; consult the skills its type implies.
4. Record: resolution comment with the answer, close it, append one line to the PRD's Decisions so far.
5. Add newly surfaced sub-issues (create, then wire blocking); turn fog the answer sharpened into sub-issues, clearing it from Not yet sharp; close and log mis-scoped ones under Out of scope; update or delete sub-issues the decision invalidated.

Expect other sessions to be editing the tracker concurrently.
