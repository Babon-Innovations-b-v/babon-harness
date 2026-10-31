# ADR Format

ADRs live in `docs/adr/` and use sequential numbering: `0001-slug.md`, `0002-slug.md`, and so on.

Create new ADRs lazily: only when the 3-condition rule below trips, **and only after the owner has
said yes to this one**. A new ADR is a new `.md`, which needs a go-ahead like any other (root
`CLAUDE.md`, ADR-0003). Offer it in one line and wait. Editing an existing ADR needs no permission.

## Template

```md
# {Short title of the decision}

**Status:** accepted

{One to three paragraphs: what the context was, what we decided, and why. The reasoning is the
value; the decision itself is usually one sentence.}
```

That is it. An ADR can be a single paragraph. The value is in recording *that* a decision was made
and *why*, not in filling out sections.

## Optional sections

Only include these when they add genuine value. Most ADRs will not need them.

- **Considered Options**: only when the rejected alternatives are worth remembering.
- **Consequences**: only when non-obvious downstream effects need to be called out.

## Numbering

Scan `docs/adr/` for the highest existing number and increment by one.

**One number, one ADR.** A number is never used twice and never reused after a delete, so
`ls docs/adr/ | grep ^NNNN` must come back empty before you write the file, and
`git log --diff-filter=D -- 'docs/adr/NNNN-*.md'` must come back empty too. Take the next free
number above the highest in use; do not fill a gap.

This matters because every citation in the tree is a bare "ADR-NNNN": a duplicate number makes
every one of those citations ambiguous, and unpicking it means renaming files and rewriting
citations across code, docs, overlays and issues. Parallel sessions are how collisions happen: two
agents both read the highest number, both increment, both commit. If you are one of several
sessions running at once, re-check the number right before you commit.
`python3 docs/adr/tools/check_index.py` fails on a duplicate, so a collision is caught before it is
committed rather than a month later.

## When to offer an ADR (the 3-condition rule)

All three of these must be true:

1. **Hard to reverse**: the cost of changing your mind later is meaningful.
2. **Surprising without context**: a future reader will look at the code and wonder "why on earth
   did they do it this way?"
3. **The result of a real trade-off**: there were genuine alternatives and you picked one for
   specific reasons.

If a decision is easy to reverse, skip it; you will just reverse it. If it is not surprising,
nobody will wonder why. If there was no real alternative, there is nothing to record beyond "we did
the obvious thing".

### What qualifies

- **Architectural shape.** "This is a monorepo." "The write model is event-sourced, the read model
  is projected into a table."
- **Integration patterns between modules.** How two subsystems are allowed to reach each other.
- **Technology choices that carry lock-in.** Database, message bus, auth provider, deployment
  target, mod loader. Not every library, just the ones that would take a quarter to swap out.
- **Boundary and scope decisions.** The explicit no-s are as valuable as the yes-s.
- **Deliberate deviations from the obvious path.** Anything where a reasonable reader would assume
  the opposite. These stop the next engineer from "fixing" something that was deliberate.
- **Constraints not visible in the code.** A rule imposed from outside: a licence, a platform
  policy, a contract, a response-time budget.
- **Rejected alternatives when the rejection is non-obvious.** Otherwise someone will suggest the
  same thing again in six months.

## Correcting versus trimming

These are different acts and only one is banned.

- **Correct in place, and you should:** a sentence that is factually false today, a status that no
  longer matches the live system, a path or tool that does not exist, a count that has moved on.
  Carry the date and the evidence with the correction, inline. A record that quietly lies is worth
  less than no record.
- **Do not trim:** shortening prose, restructuring headings, or deleting sections to normalise an
  older ADR onto a newer template. That destroys the reasoning without adding truth.
- **A decision that changed gets a dated amendment or a status line, never a rewrite.** The old
  text stays; the reader needs to see what was believed and when.

The point of the split: an ADR's *value* is its reasoning, which is why trimming is banned, and its
*usability* depends on not sending readers to things that no longer exist, which is why correcting
is expected.
