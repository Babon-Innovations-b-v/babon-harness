# Domain Awareness

Consumer rules for any skill that explores this codebase. Producer rules (writing to the glossary, offering ADRs) live in the `grill` skill.

## Before exploring, read these

- **[`CONTEXT.md`](../../CONTEXT.md)**: the glossary at the repo root. It picks the canonical term for each concept and lists the `_Avoid_:` aliases.
- **The relevant [`docs/bible.md`](../../docs/bible.md) chapter**: pick from the chapter map in root `CLAUDE.md`. Read only the chapter(s) the prompt touches; not the whole file.
- **[`docs/adr/`](../../docs/adr/)**: read the ADRs that touch the area you are about to work in. The index is `docs/adr/0000-index.md`.

If root `CLAUDE.md` names a tool that locates this reading (an orient or index tool), call it first: one word or one path, never the user's sentence, then read the ranges it names. It says where to read, not what it says; where it and the chapter map disagree, the map wins, and when it is absent or answers nothing, read by hand.

If any of these have no content for your topic, **proceed silently**. Don't flag the absence; don't suggest creating something upfront. The producer skill (`grill`) creates entries lazily, when a term or a decision actually gets resolved.

## One glossary, one bible

This repo uses one bible file (`docs/bible.md`) and one glossary (`CONTEXT.md`). No split map, no second glossary. Per-directory `CLAUDE.md` overlays are thin pointers to the relevant bible chapter, not separate contexts.

## Use the glossary's vocabulary

When your output names a domain concept (issue title, refactor proposal, hypothesis, test name, agent prompt), use the term as defined in `CONTEXT.md`. Don't drift to a synonym the glossary explicitly avoids (`_Avoid_:` line). If root `CLAUDE.md` names a glossary lookup tool, check the word with it rather than trusting memory: a ruled-out spelling reads as ordinary prose, so nothing else pushes back on it. The verdict is about prose, so a word can be wrong in a sentence and still be the right identifier, table name or commit scope.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it; the next `grill` session will fill it).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-NNNN (its one-line decision), but worth reopening because…_

Don't list every theoretical refactor an ADR forbids. Only surface a conflict when the friction is real enough to warrant revisiting the decision.

## Skills that obey this contract

- `grill` (producer and consumer)
- `brain-dump`
- `to-prd`
- `improve-codebase-architecture`
- `zoom-out`
- `diagnose`
- `prototype`
- `handoff`
- `tdd`

If you're writing a new skill that explores code, link this file as the first reference.
