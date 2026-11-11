---
name: grill
description: Pocock grill-with-docs, adapted for this repo. You're on the team but remember nothing at conversation start. Orient (prompt, soul, root CLAUDE, CONTEXT.md glossary, relevant bible chapters + overlays/MCP + related GitHub issues/PRDs), then interview the plan against the domain model, sharpening terms into CONTEXT.md inline and offering an ADR when a trade-off is decided. MUST be invoked on the first user message in any conversation in this repo.
---

# Grill (grill-with-docs)

The default grilling session, the [Pocock `grill-with-docs`](https://github.com/mattpocock/skills) pattern. Interview the plan against the existing domain model, sharpen terminology into `CONTEXT.md`, record real trade-offs as ADRs, all inline as decisions crystallise.

## A question, not a task (check this first)

A question that asks for facts rather than for work is not a task: a status question ("where does X stand", "did Z get finished"), a lookup ("what is our ..."), or an impact question ("what would I have to touch to ...", "what breaks if ..."). Skip orient, the dump check and the wayfinder check. Use the repo's index tools first (root `CLAUDE.md` names them; load them first if they arrive deferred), then ask the index first, using a ready-made query it lists when there is one; put every remaining search into ONE bundled shell call that prints a labelled report; read only the lines that call names. Check nothing the user did not ask about. Answer in this shape: the answer in two or three sentences, then at most five bullets of the things that matter most (what breaks, what to touch), then one line offering the full list. Never paste the full list unasked.

## Before asking anything (orient)

1. Read the user's prompt.
2. **Do the repo's own orient additions first, before you read or search anything else.** Root `CLAUDE.md` may name them (index or search tools to load and ask before opening files or calling `gh`, a topic-to-chapter map, which overlays bind a path). Load those tools now and put the prompt's own question to them; every later step that reads a file, a chapter or an issue goes through them first, and `gh`, `grep` or `cat` only fills what they cannot answer. A step the repo names is part of orient, not an option, and it comes first because a session follows this list in order: placed after the issue search, it was skipped. **Ask once per surface the prompt names, all in one turn**: each app, each system, each appendix of a pasted document (a consent form, a privacy promise) gets its own question to the index. One word for a many-sided prompt leaves the other surfaces dark, and their questions then go to the user instead.
3. Read `.claude/soul.md` (voice + hard rules).
4. Read root `CLAUDE.md`.
5. Read `CONTEXT.md` (the canonical domain glossary, repo root).
6. Decide which `docs/bible.md` chapters apply (chapter map in root `CLAUDE.md`). Read them.
7. Decide which agents, overlays (`<area>/CLAUDE.md`), or MCP tools apply. Load them.
8. Search GitHub for issues and PRDs that touch the prompt. Issues are where every effort is documented, so the relevant ones are half the context. Pull keywords and any `#N` from the prompt, ask the repo's index from step 2 when it holds issues, else run `search_issues` on the repo named in `.claude/project.json` (open **and** closed, since closed issues carry shipped history), and read the few that actually match: PRD body, current state, recent comments, linked sub-issues. Prefer open PRDs; a closed issue that already did this work is a signal to say so before grilling further. Skip only if the prompt is clearly issue-free (a greeting, a pure code question with no feature behind it).
9. Read the owner's newest rules: `git log origin/main --since='3 days ago' --format='%h %s' | grep -i owner`, and the same for the owner's name as this repo's commits and rules write it (the owner handle is `owner` in `.claude/project.json`). A rule can land minutes before the work it governs. Any that touch the plan go into the plan, and into every agent brief written from it.
10. If this conversation will **write files** and root `CLAUDE.md` asks writing sessions to work in their own worktree, enter one before writing anything: `EnterWorktree({name: "<slug>"})`, where the slug is `<issue-number>-<two-to-four-kebab-words>` when the session serves an issue and `x<mmdd>-<words>` when it does not. Then run `bash .claude/scripts/worktree-setup.sh` if the repo has one, and push from there with `git push origin HEAD:main`. A read-only session (a question, a review, a research pass) stays in the shared checkout.

If a *fact* can be found by exploring the codebase or the backlog, look it up instead of asking. The *decisions* are the user's: put each one to them and wait for the answer. Consume-rule in [`.claude/skills/DOMAIN-AWARENESS.md`](../DOMAIN-AWARENESS.md): read `CONTEXT.md` + the relevant bible chapter + the area's ADRs first; flag ADR conflicts.

## Dump check (right after orient, before the wayfinder check)

Is this message a **brain dump** rather than a task? Signals: several open questions at once,
visionary thinking, a pasted conversation, "here is everything I have been thinking". If yes, say
so in one line and invoke [`brain-dump`](../brain-dump/) immediately; it sorts the dump into
claims, questions, decisions and vision, then sweeps and lands each in its own home. Do not
interview a dump into shape first; sorting it is what that skill does.

One question, however broad, is not a dump. Continue below.

## Wayfinder check (right after orient)

Ask yourself one question before interviewing: **is this a wayfinder-sized effort?**, too big for one session, and fogged (the way to the destination is not visible yet, too many open decisions to resolve in one sitting). If yes, say so in one line and invoke the [`wayfinder`](../wayfinder/) skill immediately; it charts the effort as a PRD with investigation sub-issues, grilling one question at a time. If no (the normal case), continue below.

**Route immediately, don't interview first.** Fogged opening prompt (goal is a direction not a plan, "I want to build something that…", "get to more layers") fires wayfinder on the first reply. Don't grill it into focus first; wayfinder does the one-question charting. When unsure it's fogged enough, it is.

## Your first reply (keep it short)

Orientation is silent, issue-reading included. The reading in steps 1-9 fills your context, it does not get reported back; do not open with a list of the related issues you found. The one exception is a closed or in-flight issue that already covers the ask: name it in one line so the user can redirect before you grill the wrong thing. A rich knowledge base pulls you to dump findings; don't. Verbosity is the most common complaint about this loop.

First reply = one sharp question, plus one line of context only if needed. No summary, no findings list, no options menu. When in doubt, cut it.

## During the session

Interview the user relentlessly about every aspect of the plan until you reach a shared understanding. Walk down each branch of the design tree, resolving dependencies one-by-one. For each question, give your recommended answer. **Check before you ask**: before a question goes to the user, put its subject to the repo's index (orient step 2) and search the code it names; ask only if neither settles it. A question whose answer is already built or already decided costs the user a round-trip and shows you did not look. **Ask one question at a time, waiting for the answer before the next**, asking multiple questions at once is bewildering. Every reply stays short: one question, minimal context, then stop.

### Challenge against the glossary

When the user uses a term that conflicts with `CONTEXT.md`, call it out immediately. "CONTEXT.md defines _trial_ as X, but you seem to mean Y, which is it?"

### Sharpen fuzzy language

When the user uses a vague or overloaded term, propose a precise canonical one. "You are saying _the worker_. Do you mean the process that picks the job up, the container it runs in, or the thing that deploys it? Those are three different things."

### Discuss concrete scenarios

Stress-test domain relationships with specific scenarios. Invent edge cases that force precision about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. On a contradiction, surface it: "You said every run writes a manifest, but the gate skips it when the run is quarantined. Which is right?"

## Inline writes (as you grill, not batched)

1. **A term gets sharpened** → `Edit` `CONTEXT.md` to add/refine it, opinionated CONTEXT format (definition + `_Avoid_:` aliases), per [Pocock CONTEXT-FORMAT](CONTEXT-FORMAT.md). `CONTEXT.md` is glossary only, no implementation detail leaks in. Group under the right subheading.
2. **A load-bearing invariant is confirmed** (one that a future reader would otherwise re-derive from the code) → `Edit` the relevant `docs/bible.md` chapter to surface it.
3. **A real trade-off is decided** → record it where it was decided (the issue, and its bible chapter when it is load-bearing). Do **not** write an ADR on your own: offer it in one line ("want this as an ADR?") and write it only after the owner says yes, per [`docs/adr/ADR-FORMAT.md`](../../../docs/adr/ADR-FORMAT.md). New `.md` files, ADRs included, need a go-ahead (root CLAUDE.md).

Otherwise no write. Conversation-derived insight flows through grill; code-derived drift gets fixed by hand (no automated doc-sync).

Do not enact the plan until the user confirms shared understanding is reached.

## Routing on completion

When shared understanding is reached, invoke the next skill:

- **First message contained `#N` or a GitHub issue URL** → `to-prd` in resume mode (re-align against the existing issue body; amend if drift).
- **Otherwise** → `to-prd` (synthesises the aligned plan as a PRD-style issue; it also carves a sub-issue under the PRD when a task is independently grabbable or going ready-for-agent).

The flow is always `grill → to-prd → code → close`. Two branches: the dump check sends a brain dump to `brain-dump`, and the wayfinder check sends fogged multi-session efforts to `wayfinder`.
