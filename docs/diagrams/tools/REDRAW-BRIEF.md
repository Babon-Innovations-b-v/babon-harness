# Draw a page in the diagram set's design system

Every page is drawn through the `diagram` MCP (`draw_module`), which writes two
spec files and builds the page. This brief is what those two files must say.
Simple pages that can be told one click at a time, a shape chosen per page
instead of one template, plain words, no crossing lines.

## What you write (two files, nothing else outside your page)

`docs/diagrams/specs/stack/<page>.json`, the facts:

```
{"title": "...", "subtitle": "one honest line, no marketing",
 "legend": {"backend": "...", "edge-emphasis": "...", "edge-dashed": "...",
            "edge-default": "..."},          // name every kind you use, edges too
 "nodes": {"<id>": {"type": "backend", "label": "plain name",
                    "sublabel": "2-4 words", "note": "2-4 sentences",
                    "bible": "the text that claims this box in the bible",
                    "module": "other-page.html",     // only where a drill-down exists
                    "code": ["infra/auto-deploy/steps/40-gate.sh"]}},  // what this box draws
 "slides": [{"label": "what this step says", "add": ["id", "from-to", ...]}]}
```

`docs/diagrams/specs/stack/<page>.layout.json`, the shape:

```
{"_comment": "one line saying what shape this page is and why",
 "canvas": [W, H],
 "boxes": {"id": [x, y]},                    // top-left corners, 150x62 default
 "sizes": {"id": [w, h]},                    // optional
 "boundaries": [{"label": "...", "wraps": ["id", ...]}],
 "edges": [["from", "to", "label or empty", {"variant": "dashed"}]]}
```

### `code`: what a box draws

Optional, a list of repository paths, files or directories, no line numbers.
Write it while you draw, for the boxes that have code behind them; a person, a
timer, an outside service or a way of working leaves it out. Nothing can work
this out from a box id, which is why it is written by hand. `linkmap.py`
refuses a path that is not in the checkout, so the field cannot quietly rot,
and it asks a person to re-read a box when the code it names changes.

Build with `python3 docs/diagrams/tools/build_free.py stack/<page>` until it
prints `built:` and exits 0. That writes the sidecars into
`docs/diagrams/data/stack/` and the html into `docs/diagrams/stack/`. The top
page is `stack` itself (`build_free.py stack`).

## The design system

- **The shape is the argument.** Pick the shape the content has: a chain left
  to right, a funnel, a tree, two streams meeting, a ring, one door fanning
  out. Say the shape in `_comment`.
- **Six boxes, a ceiling and not a target.** Merge the thin ones into a
  neighbour's note; a box earns its place by having something to say.
- **One entry point.** Slide 1 is where a first-time reader starts: a single
  box or one tight region.
- **Slides tell it.** 4 to 6 steps, each adding the boxes and edges of one
  idea, labels that narrate rather than headings. Edge ids in `add` are
  `from-to`. Every box and edge appears in some step.
- **No crossing lines.** build_free routes automatically; when two edges share
  a lane or cross, place explicit `fromSide`/`toSide`/`via` or move boxes.
  Verify with a screenshot.
- **Captions never repeat the arrow.** An edge label says what moves or why it
  matters, or is empty.
- **Regions carry structure, and the bible borrows it.** Tinted named
  boundaries group what belongs together, and their labels become the `### `
  section headings of the chapter that claims this page, copied as written. So
  a region label names its subject.
- **A box label is the thing's real name** where it has one: `node-exporter`,
  not "The machine". A name you can grep for and find in the config.
- **Notes have a fixed shape.** Name, address and cadence on one line; what it
  does and why it is that shape; then a bolded **Watch out:** carrying what
  will bite a reader. Real names and numbers. Never invent a number.
- **A note is read in one look.** A one-fact box is 15 to 25 words, an ordinary
  one 30 to 45, a box carrying real machinery up to 70.
- **The note is where an enumeration belongs**, written as sentences: return
  codes, the chain of step filenames, every flag of a command.
- **House voice.** Everyday words, English only, no em dashes, no jargon the
  glossary (CONTEXT.md) does not carry.

## Hard mechanics

- Grid that works: x steps of about 240 (boxes 150 wide plus 90 gap), y steps
  of 140 to 150. Leave about 130px of canvas height under the lowest box or the
  legend fails validation with `legend/vertical-overflow`.
- Legend keys: node kinds (`external`, `frontend`, `backend`, `database`,
  `cloud`, `security`, `messagebus`, `money`) plus `edge-emphasis`,
  `edge-dashed`, `edge-money`, `edge-default`. Unnamed edge kinds render as
  "primary flow"/"secondary flow"; never leave those defaults.
- Screenshot check, the only way to catch overlaps: open the page in a headless
  Chromium at 1900x1000 and read the png, then do the same for `#step=1`.
- **Box ids stay stable when the concept survives.** The bible claims each box
  by id; a kept id keeps its sentence.
- **Never edit docs/bible.md from a drawing pass.** The linkmap hook complains
  about unclaimed boxes while a page is in flux; the bible section is written
  in the same session, by whoever is building the module.
