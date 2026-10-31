# ADR Index

Architectural Decision Records: hard-to-reverse choices, invariants we live with, and known
operational risks. One ADR per decision, numbered sequentially. New ADRs only when a decision is
hard to reverse, surprising, and trades off genuine alternatives, **and only after the owner has
agreed to that ADR**: a new record is a new file and needs a yes like any other (root `CLAUDE.md`,
ADR-0003). See [ADR-FORMAT.md](ADR-FORMAT.md).

Gaps in the numbering are deleted or never-used IDs. **Numbers are never reused.**

**The file's own status line is authoritative; this index mirrors it.** `docs/adr/tools/check_index.py`
enforces the mirror, so it cannot drift silently.

## Status vocabulary

Five values, nothing else. Freehand status prose is what makes an ADR set untrustworthy.

| Status | Means |
|---|---|
| `accepted` | live and binding |
| `accepted; amended by NNNN` | still binding, with a later clarification |
| `superseded (in part) by NNNN` | a later decision replaced it, wholly or in the named part |
| `reversed <date>` | we changed our mind; the file keeps the original reasoning |
| `proposed` | not decided yet. If it is running in production it is not `proposed` |

## Live decisions

Grouped by the same areas as the bible chapter map in root `CLAUDE.md`. The bucket is what you
navigate by; the number stays flat and sequential forever, because every citation in the tree is a
bare "ADR-NNNN".

### Workflow

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-main-only-no-feature-branches.md) | Work on `main` only, no feature branches | accepted |
| [0002](0002-no-loose-files-outside-the-carve-out.md) | No loose files outside the carve-out | accepted |
| [0003](0003-a-new-markdown-file-needs-a-yes.md) | A new markdown file needs the owner's go-ahead | accepted |
| [0004](0004-one-language-on-the-engineering-surface.md) | One language on the engineering surface | accepted |

### Architecture

<Empty. The first architectural decision this project makes lands here.>

### Historical

Superseded and reversed records. They stay readable: the reasoning is the value, and a later reader
needs to see what was believed and when.

<Empty.>

## Checking the index

```bash
python3 docs/adr/tools/check_index.py
```

It fails when a file has no row, a row points at no file, a status disagrees with its file, a
retired record still sits in a live table, or the carve-out list in ADR-0002 and root `CLAUDE.md`
have drifted apart.
