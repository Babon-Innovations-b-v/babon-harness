---
name: brain-dump
description: Turn a dump of vision, claims and open questions into documents, glossary terms, decisions and issues that fit this repo, with the least ambiguity possible. Sort, sweep, refute, land, merge, chart, check; it simplifies and merges harder than it adds. Use when a message is a dump rather than a task (several open questions at once, visionary thinking, a pasted conversation, "here is everything I have been thinking"), when grill's dump check fires, or when the user invokes /brain-dump.
---

# Brain dump

A page of thinking arrives. The job is to put that same thinking into the system with every word
defined once, every number in one place with its source, and every loose end either an issue or
named as fog. **Ambiguity is the thing being removed**, not volume.

It spends many agents, so it earns its cost only on a real dump: one question is a `grill`
question, a known effort that is merely big is [`wayfinder`](../wayfinder/). Exploring code
follows [`../DOMAIN-AWARENESS.md`](../DOMAIN-AWARENESS.md).

## 1. Sort, before any agent runs

Split the dump into four kinds. Sorting badly poisons everything downstream, and it is the one
place ambiguity is still cheap to fix.

| Kind | What it is | Where it goes |
|---|---|---|
| **Claim** | Checkable against the world or the repo | A sweep |
| **Question** | Open, and answerable at a desk | A sweep |
| **Decision** | Only the user can make it | Straight back to them, never to an agent |
| **Vision** | The direction that decides what counts as an answer | The brief every agent reads |

Read those four lists back in one short message and get the sort confirmed. Wrong kinds are the
expensive mistake: a decision routed to a sweep comes back as an agent picking a price or a date
on the user's behalf. *Done when every line sits in exactly one list.*

## 2. Sweep

One `Workflow`, parallel agents, one distinct angle each, returning structured findings where
**every claim carries a URL, a repo path or an issue number**. Give one agent the job of finding
what is being forgotten; that is where the useful findings come from. *Done when every angle
returned or is named as failed.*

**Every agent writes its findings to a file in `/tmp` and returns the conclusion, never the
trawl.** The session holds summaries, the files hold the evidence, and nothing an agent trawls is
committed. That is what makes a round this size fit in one context window. Three or four sweeps
for something that exists, five or six for something new; past that add rounds.

## 3. Refute

One verifier per sweep, each given a **distinct lens phrased as the reader who would catch it**
("would the person this concerns recognise their own numbers?"), told to refute rather than check
and to default to killing. *Done when every kept claim has a source someone opened.*

## 4. Land

Each kind goes to its own home, one writer per home, with **strict file ownership named in the
prompt** so parallel writers never touch the same file.

| What came out | Where it lands |
|---|---|
| A new word | [`CONTEXT.md`](../../../CONTEXT.md) **first**, so the documents can use it |
| A trade-off that is hard to reverse, surprising, and real | The issue it belongs to, plus a one-line offer of an ADR; write the ADR only after the user says yes, per [`docs/adr/ADR-FORMAT.md`](../../../docs/adr/ADR-FORMAT.md) |
| A figure | The set's **fact store**, with its source and its confidence |
| The thinking itself | One file per subject, in a fixed section order |
| A load-bearing invariant | Its `docs/bible.md` chapter, via the map in root `CLAUDE.md` |
| A document that now exists | Its row in the index of whatever set it belongs to |

**The governing rule, in the set's README: a document may not state a number that is not in the
fact store.** If it needs one, the figure goes there first, or it is marked unverified in the same
sentence every time. Keep an **assumption register** beside it: the value, what it rests on, how
confident, what would settle it. That register is what makes the set arguable rather than merely
confident. *Done when every survivor is in one home.*

## 5. Merge, before anything is created

**The default is fewer things, not more.** Every round adds; nothing removes unless this step
does, and a flat list of siblings is what that looks like after a few rounds. Apply to issues and
files alike:

- **The one-session test.** Would one person, in one sitting, do both? Then they are one item with
  a checklist, not two items. A sequence of steps is one issue with checkboxes.
- **The one-conversation test.** Settled by the same conversation with the same person? One item.
- **Seven is the ceiling.** A parent with more than about seven open children is a list, not a
  plan. Group them under a real intermediate, or merge until it is a plan again.
- **A new item must earn its number.** Editing something that exists beats creating something new.
- **One parent, matching subject.** If you cannot name the parent without arguing, the parent is
  wrong or the item is two items. Never park an item under the nearest big thing.
- **Containers are fluid.** A PRD is a container for an effort, not a permanent object. One that
  no longer matches the work gets merged into its neighbour, split, or closed, and its children
  move with the work rather than with the container's history. **Count the active ones, never the
  total**: long-term planning is supposed to park containers for later, so a parked one is the
  system working. Active means the board says so, In Progress or in the now horizon. One person
  carries several at once, not many; too many active at once is the finding.
- **When in doubt, merge.** Splitting later is cheap. A flat board is not, and nobody unpicks it.

Merging never loses a named person, a date, or a promise made outside the company: those move
across verbatim. *Done when no parent has more than about seven open children.*

## 6. Chart

What survives the merge becomes issues, never a list inside a document. Hand the route to
[`wayfinder`](../wayfinder/): a PRD with sub-issues typed
`wayfinder:research|prototype|grilling|task`, one resolved per session.

The planning agent returns the set as data and creates nothing; you create it, so it is read
before it hits the board. Then burn the research ones down the wayfinder way: one subagent each,
any number in parallel, each closing its sub-issue with a resolution comment. Every issue gets an
assignee at creation, its area label when the project has areas (`.claude/project.json`), and **a
link to the document it serves, with the document linking back**. *Done when every open question is
an issue or a line of fog, and no parent has more than about seven open children.*

## 7. Check

One agent that opens files rather than trusting the writers' reports: links tested, registry
matched against the tree both ways, house rules searched for. Expect it to fail the first time; a
check that never fails is a check nobody reads. *Done when it names its evidence.*

## Rules the round is built from

- **Any open research question fires an agent immediately.** A question a desk can answer never
  waits for a phase boundary, a session or a human: spawn it the moment it surfaces, any number in
  parallel, answering as confidently as its sources allow. Only decisions queue.
- **Never answer the user's decision.** It comes back as a decision, with a recommendation.
- **A named gap beats a guess.** "Not public, and here is what would settle it" is a finding.
- **Never merge away a named person, a date, or a promise made outside the company.**
- **Record the kill list** with reasons, in the fact store, so nobody researches it twice.
- **Confidence travels with the claim**, in the same sentence, every time.
- **Length tracks the reader.** Past where the reader would stop, split by purpose.
- **A round that only adds has failed.** Every round merges or closes something. Report the count.
