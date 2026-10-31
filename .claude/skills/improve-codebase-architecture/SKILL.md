---
name: improve-codebase-architecture
description: Scan this codebase for deepening opportunities, informed by the CONTEXT.md glossary and the decisions in docs/adr/ and the bible, present them as a visual HTML report outside the repo, then grill through whichever one the user picks. Use when the user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make a codebase more testable and AI-navigable.
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities**: refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

This skill is _informed_ by the project's domain model and built on a shared design vocabulary:

- Call the Skill tool with "codebase-design" for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly in every suggestion, and don't drift into "component," "service," "API," or "boundary."
- The domain language in [`CONTEXT.md`](../../../CONTEXT.md) gives names to good seams; ADRs in `docs/adr/` and the invariants in [`docs/bible.md`](../../../docs/bible.md) record decisions this skill should not re-litigate. The house bar for a module is [`docs/bible.md#workflowmodule-standard`](../../../docs/bible.md#workflowmodule-standard).

## Process

### 1. Explore

**Scope before you scan: YAGNI.** Deepening a module pays off by making future changes to it easier, so put extra weight on the parts of the codebase that have recently changed. Decide *where* to look before you look:

- If the user named a direction (a module, a subsystem, a pain point), take it, and skip the inference below.
- Otherwise, walk back a good stretch of the commit history (`git log --oneline`) to find the codebase's hot spots, the files and areas that keep coming up, and let those paths pull your attention first. If the changes are scattered with no clear hot spot, widen the net.

Before exploring, follow [../DOMAIN-AWARENESS.md](../DOMAIN-AWARENESS.md): read `CONTEXT.md`, the relevant bible chapter, and any ADRs that touch the area first.

Then use the Agent tool with `subagent_type=Explore` to walk the codebase. Don't follow rigid heuristics; explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow**, with an interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want. Count before you judge: the files that import the suspect directly are who would pick its complexity up, and the transitive importers are how far it travels. If root `CLAUDE.md` names an index tool that answers "who imports this path", ask it rather than grepping; half a dozen of those counts give a table you can compare, and the comparison is the candidate list. Importer counts are file-level: they say how many files would have to change, never how many call sites.

### 2. Present candidates as an HTML report

The report never lands in the repo. Write one self-contained HTML file to the job's scratch directory when there is one, otherwise to `${TMPDIR:-/tmp}/architecture-review-<timestamp>.html` so each run gets a fresh file, and tell the user its absolute path. Or publish it as an Artifact, following the host's own artifact guidance when it has any; the scaffold notes in [HTML-REPORT.md](HTML-REPORT.md) say what changes for that.

The report uses **Tailwind via CDN** for layout and styling, and **Mermaid** for diagrams where a graph/flow/sequence reliably communicates the structure. Mix Mermaid with hand-crafted CSS/SVG visuals: use Mermaid when relationships are graph-shaped (call graphs, dependencies, sequences), and hand-built divs/SVG when you want something more editorial (mass diagrams, cross-sections, collapse animations). Each candidate gets a **before/after visualisation**. Be visual.

For each candidate, render a card with:

- **Files**: which files/modules are involved
- **Problem**: why the current architecture is causing friction
- **Solution**: plain English description of what would change
- **Benefits**: explained in terms of locality and leverage, and how tests would improve
- **Before / After diagram**: side-by-side, custom-drawn, illustrating the shallowness and the deepening
- **Recommendation strength**: one of `Strong`, `Worth exploring`, `Speculative`, rendered as a badge

End the report with a **Top recommendation** section: which candidate you'd tackle first and why.

**Use `CONTEXT.md` vocabulary for the domain, and the `codebase-design` vocabulary for the architecture.** If `CONTEXT.md` defines **route**, talk about "the route module," not "the FooBarHandler," and not "the route service."

**ADR conflicts**: if a candidate contradicts an existing ADR or a bible invariant, only surface it when the friction is real enough to warrant revisiting it. Mark it clearly in the card (e.g. a warning callout: _"contradicts ADR-NNNN, but worth reopening because…"_). Don't list every theoretical refactor an ADR forbids.

See [HTML-REPORT.md](HTML-REPORT.md) for the full HTML scaffold, diagram patterns, and styling guidance.

Do NOT propose interfaces yet. After the report is written, ask the user: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, walk the decision tree with them under the `grill` skill's session discipline, one question at a time: constraints, dependencies, the shape of the deepened module, what sits behind the seam, what tests survive.

Side effects happen inline as decisions crystallize, with the same inline-write triggers as `grill`:

- **Naming a deepened module after a concept not in `CONTEXT.md`?** Add the term to `CONTEXT.md` in its format (canonical term plus `_Avoid_:` aliases), lazily, under the section it belongs to.
- **Sharpening a fuzzy term during the conversation?** Update `CONTEXT.md` right there.
- **User rejects the candidate with a load-bearing reason?** Offer an ADR in one line: _"Want me to record this as an ADR so future architecture reviews don't re-suggest it?"_ Write it only after the owner's yes, in the [`docs/adr/ADR-FORMAT.md`](../../../docs/adr/ADR-FORMAT.md) format; otherwise the reason goes on the issue where it was decided, and into its bible chapter when it is load-bearing. Only offer when a future explorer would need the reason to avoid re-suggesting the same thing; skip ephemeral reasons ("not worth it right now") and self-evident ones.
- **Want to explore alternative interfaces for the deepened module?** Call the Skill tool with "codebase-design" and use its design-it-twice parallel sub-agent pattern.
