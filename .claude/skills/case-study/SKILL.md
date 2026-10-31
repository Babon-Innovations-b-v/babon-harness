---
name: case-study
description: Draw a module or a stretch of progress as a page in the diagram set, from verified facts, every box claimed by a piece of text in the bible. Use when the user invokes /case-study, and whenever a module is built or meaningfully changed (a module is drawn alongside the work).
---

# Case study

The deliverable is a page in the diagram set: one drawing of one thing, mined from the code, tellable a step at a time, with every box claimed by one piece of text in the bible, a word or a table row or a bullet or a paragraph, whichever explains it. A written note is the rare long form and comes last; the page is the product.

**Drawing is part of building.** When a module is built or meaningfully changed, its page is drawn in the same session, by you, without being asked, and its bible section is written in the same pass. Drawn is not published: the page sits in the set where a reader could click down to it, and nobody is sent there. It goes in front of a person at exactly one moment, when the work needs review or feedback, and the address goes in the issue so the conversation happens over the drawing instead of over a diff. A hook (`.claude/hooks/local/diagram_watch.py`) names the areas this session touched whose page is missing or did not move with the code; it reminds, it never blocks, because a wrong drawing is worse than a missing one.

**Three calls, not thirty commands.** The `diagram` MCP (`python3 docs/diagrams/mcp/server.py`, registered in `.mcp.json`) owns the pipeline: `draw_module(name, spec, layout)` writes the two spec files, routes the edges, builds, delivers, wires the popups and hands back the ◈ markers the bible still owes; `link_module(name, parent_node)` hangs the page off a box on the page one level out and returns the address to paste; `check_diagrams()` reads the whole set both ways. The two files, the field names, the legend keys, the working grid and the screenshot check live in [`docs/diagrams/tools/REDRAW-BRIEF.md`](../../../docs/diagrams/tools/REDRAW-BRIEF.md). Read it before writing a spec. This skill is the method; that file is the manual.

## What a page is

Facts and shape, in two files. `docs/diagrams/specs/stack/<page>.json` is what is true: title, one honest subtitle, a legend that names every kind used including the edges, the boxes with their popup notes and the bible text that claims each one, and the slides. `<page>.layout.json` is where it sits: canvas, box corners, the named regions, the edges. `build_free.py` turns the pair into the build sidecars under `docs/diagrams/data/` and the served page (it drives the archify skill's renderer through `deliver.sh`; you never run archify by hand). The top page is `stack` itself and every other page hangs under it.

There is no page template. **The shape is the argument:** a chain left to right, a funnel, a ring, two streams meeting, one door fanning out. Take the shape the content already has and say which one it is in the layout's `_comment`.

## Drawing one

1. **Take the facts from the code**, never from another diagram and never from memory. Anything load-bearing gets checked in the repo. Never invent a number, never soften a failure. The repository index (`.mcp.json`'s `index` server) answers who imports a directory, what starts it and which commits made it; when it is absent, read the tree by hand.

2. **Cut until every box says something.** Six boxes, a ceiling and not a target. A thin box folds into a neighbour's note; a whole family folds into one box that opens its own page. Depth is another page, not a denser drawing. Each note has a fixed shape: the name, the address and the cadence on one line; then what it does and why it is that shape; then a bolded **Watch out:** for the thing a reader must not get wrong, in the present tense. A one-fact box is 15 to 25 words, an ordinary one 30 to 45, a box with real machinery up to 70. The note is where an enumeration belongs (return codes, step filenames, flags), written as sentences.

3. **Place the boxes by hand in the shape you chose**, with tinted regions whose labels name what is inside them. A box label is the thing's real name where it has one, a name you can grep for. A region label becomes the bible section's heading. No crossing lines. A caption says what moves or why it matters, or it is empty.

4. **Write the slides.** Step one opens on a single box or one tight region, so a first-time reader sees where to start. Four to six steps after that, each carrying one idea. Every box and every edge arrives in some step.

5. **Wire it, both ways.** A new page needs a home: a box on the page one level out has to open it, which is what `link_module` writes into that parent's module map. Without a home the page is stranded and `linkmap.py` fails. The zoom-out button lands on the page that opens it, never sideways to a sibling.

6. **Claim every box in the bible.** One piece of text per box, inside the `###` section that talks about it, ending with its marker. With `BIBLE_BASE_URL` unset the marker is relative to `docs/bible.md`, `[◈](diagrams/stack/<page>.html#focus=<box>)`; with it set, the published address goes in front, `[◈](<BIBLE_BASE_URL>/diagrams/stack/<page>.html#focus=<box>)`. `draw_module` hands back the exact markers owed. `linkmap.py` writes every page's `links.json` from those markers and fails on a box nothing claims, a box two claim, or a marker outside a section. Keep a box id when the concept survives and its claim stays with it. Re-deliver the pages linkmap prints, or their popups keep the old target.

7. **Look at it.** Screenshot the finished page and step one, and read the images. Overlaps, a line crossing a box and a legend running off the canvas are found by eye, not by a validator.

8. **Only then, and only when the work needs a human,** put the address in the issue or the review.

Done when: the build exits 0, `linkmap.py` exits 0, `check_diagrams()` comes back clean, the screenshots were read, the page has a home and a way back, and every box has its claim.

## What redraws teach

- **Fewer boxes say more.** Each dropped box moves its fact into a neighbour's note or into the page below it.
- **A page whose group already says everything should not exist.** `check_diagrams()` reports pages that echo their group and never fails on it, because that judgement belongs to a reader.
- **For a page that really matters, draw it three ways** and let readers who meet it cold pick. Use it where the page carries an argument, not for a routine module map.

## When the work also earns a note

Rare, and only for a piece that has to stand on its own outside the repo. Mine the facts with the Mine protocol in [`MINE-AND-REFUTE.md`](../MINE-AND-REFUTE.md), write in the voice of [REGISTER.md](REGISTER.md) with the diagrams leading and the prose carrying only the why, the proof and the caveats, then run the Refute protocol over it. Under roughly 1,200 words before references. Ask before creating the file.

Shipping is a push to main: the pages under `docs/diagrams/` are published with the next deploy, at `BIBLE_BASE_URL` when the owner set one.
