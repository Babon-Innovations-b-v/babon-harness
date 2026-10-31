"""page_faults: every reason a page would embarrass whoever signed it.

Owns the pre-flight that the build cannot give in time. ``build_free.py``
drops an edge whose endpoint was never placed and a slide step naming an id
the page does not carry, both without a word; the renderer only says
``legend/vertical-overflow`` after a minute of rendering; and a page with no
slides builds perfectly and then cannot be told. Everything checked here is
mechanical: placement, story coverage, legend keys, whether a label fits its
box, whether the canvas leaves room for the legend.

Does NOT own taste. Whether the shape suits the argument, whether ten boxes
are the right ten, whether a note is true: that is
``docs/diagrams/tools/REDRAW-BRIEF.md`` and a human reading the screenshot.
It also does not own delivery; the build stays the authority.

FAILURE POLICY: pure and total. It reads no file, writes nothing, and never
raises: a malformed spec comes back as a fault in the list, because the caller
is an agent that should be told what to fix, not handed a traceback. An empty
list means "nothing mechanical is wrong", never "this page is good".

Provenance: the geometry constants mirror archify, which is the thing that
will actually refuse the page later:
``.claude/skills/archify/renderers/architecture/render-architecture.mjs``
(label fit, margin, legend band) and ``renderers/shared/legend.mjs`` (row
maths). If archify's geometry changes, change these with it.
"""
from __future__ import annotations

import math

# build_free.py's default box, and the fields it reads off every node: all four
# have to be there or the build dies on a KeyError, but a box is allowed to say
# nothing under its name.
BOX = (150, 62)
NODE_FIELDS = ("type", "label", "sublabel", "note")
NODE_FIELDS_SAID = ("type", "label", "note")

# What the renderer will measure. A label is refused at
# textUnits(label) * 6.6 > width + 8; the sublabel is drawn at font-size 9 and
# is not validated at all, so it is held to the same ratio here.
LABEL_ADVANCE = 6.6
SUBLABEL_ADVANCE = 9 * 0.62
FIT_SLACK = 8

# The legend sits in a band at the foot of the canvas: its first row starts at
# canvas height - 46, and it must clear the lowest drawn thing by 8px, so a
# one-row legend needs 54px of canvas under the lowest box. Every extra row
# costs another 22.
PAGE_MARGIN = 40
LEGEND_BAND = 54
LEGEND_ROW_GAP = 22
LEGEND_ITEM_GAP = 22
LEGEND_FONT = 8
LEGEND_ADVANCE = 0.62
LEGEND_BADGE = 21
# swatch width and gap: a node kind draws a small square, an edge kind a line
LEGEND_SWATCH = {"node": (14, 7), "edge": (34, 9)}
# A region is drawn 20px below its lowest member, which is what the legend has
# to clear on a page whose bottom row sits inside a boundary.
BOUNDARY_BOTTOM = 20

NODE_KINDS = ("frontend", "backend", "database", "cloud",
              "security", "messagebus", "external", "money")
EDGE_KINDS = ("edge-emphasis", "edge-default", "edge-security",
              "edge-money", "edge-dashed")
LEGEND_ORDER = NODE_KINDS + EDGE_KINDS


def _pair(value, default: tuple[int, int] | None = None) -> tuple[float, float] | None:
    """Two numbers, or the fallback: a spec is written by hand and can be wrong."""
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(number, (int, float)) for number in value)):
        return (value[0], value[1])
    return default


def _boxes(layout: dict) -> dict:
    """Where the page puts each box, or nothing when the shape is not a map."""
    boxes = layout.get("boxes")
    return boxes if isinstance(boxes, dict) else {}


def _sizes(layout: dict) -> dict[str, tuple[float, float]]:
    """Every placed box's size, the default filled in the way build_free does."""
    given = layout.get("sizes")
    if not isinstance(given, dict):
        given = {}
    return {box: _pair(given.get(box), BOX) or BOX for box in _boxes(layout)}


def _facts(spec: dict) -> dict[str, dict]:
    """The nodes that are shaped like nodes; the rest are reported, not read."""
    nodes = spec.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    return {box: node for box, node in nodes.items() if isinstance(node, dict)}


def _edge_kind(edge: list) -> str:
    """The legend kind an edge asks for; an edge with no variant is the default."""
    options = edge[3] if len(edge) > 3 and isinstance(edge[3], dict) else {}
    return "edge-" + str(options.get("variant") or "default")


def _code_faults(box, code):
    """What is wrong with a box's list of the files it draws, if it gave one.

    The field is optional and a box may leave it out when it is a
    person, a timer, an outside service or a way of working. What is refused is
    a field that is there and is not usable: not a list, a path that is not
    inside the repository, or a path carrying a line number. Line numbers are
    refused rather than trimmed, because a line number would be wrong within a
    week and the author should learn that here rather than by watching the
    check rot.

    Existence is not checked here. That belongs to
    docs/diagrams/tools/linkmap.py, which sees the whole set and runs on every
    edit to it, so a file renamed months after the page was drawn is caught in
    the session that renames it.
    """
    if code is None:
        return []
    if not isinstance(code, list) or not all(isinstance(path, str) for path in code):
        return [f"node '{box}' has a code field that is not a list of paths"]
    faults = []
    for path in code:
        if not path.strip():
            faults.append(f"node '{box}' has an empty path in its code field")
        elif path.startswith("/") or ".." in path.split("/"):
            faults.append(f"node '{box}' names '{path}', which is not a path "
                          f"inside the repository")
        elif ":" in path:
            faults.append(f"node '{box}' names '{path}' with a line number; "
                          f"paths only, a line number is wrong within a week")
    return faults


def _edges(layout: dict) -> list[list]:
    """The edges the shape lists, or nothing when it does not list them as one."""
    edges = layout.get("edges")
    return [edge for edge in edges if isinstance(edge, (list, tuple))] \
        if isinstance(edges, list) else []


def _drawn_edges(layout: dict) -> list[list]:
    """The edges that will survive the build: both ends placed."""
    boxes = _boxes(layout)
    return [edge for edge in _edges(layout)
            if len(edge) >= 2 and edge[0] in boxes and edge[1] in boxes]


def _placement_faults(spec: dict, layout: dict) -> list[str]:
    """Facts and shape have to name the same boxes, or the page loses one silently."""
    nodes = _facts(spec)
    given = spec.get("nodes") if isinstance(spec.get("nodes"), dict) else {}
    boxes = layout.get("boxes") if isinstance(layout.get("boxes"), dict) else {}
    faults = [f"node '{box}' is not a set of facts" for box in sorted(set(given) - set(nodes))]
    for box in sorted(set(nodes) - set(boxes)):
        faults.append(f"node '{box}' has facts but no place in layout.boxes, "
                      f"so it would not be drawn at all")
    for box in sorted(set(boxes) - set(nodes)):
        faults.append(f"box '{box}' is placed but has no entry in spec.nodes, "
                      f"so the build cannot say what it is")
    for box in sorted(set(nodes) & set(boxes)):
        for field in NODE_FIELDS:
            if field not in nodes[box]:
                faults.append(f"node '{box}' has no {field}, and the build reads "
                              f"all four fields off every node")
            elif field in NODE_FIELDS_SAID and not str(nodes[box][field]).strip():
                faults.append(f"node '{box}' has an empty {field}")
        faults += _code_faults(box, nodes[box].get("code"))
    if layout.get("edges") and not _edges(layout):
        faults.append("layout.edges is not a list of [from, to, label] edges")
    for edge in _edges(layout):
        if len(edge) < 2:
            faults.append(f"edge {edge} needs a from and a to")
            continue
        for end in edge[:2]:
            if end not in boxes:
                faults.append(f"edge {edge[0]} to {edge[1]} names '{end}', "
                              f"which is not a box on this page; build_free "
                              f"drops that edge without saying so")
    seen = set()
    for edge in _drawn_edges(layout):
        pair = f"{edge[0]}-{edge[1]}"
        if pair in seen:
            faults.append(f"two edges share the id '{pair}', so a slide can "
                          f"only ever add one of them")
        seen.add(pair)
    return faults


def _story_faults(spec: dict, layout: dict) -> list[str]:
    """Every page is told one step at a time, and every box takes a turn.

    Edges are not held to that. The player draws a line as soon as both its
    ends are on the page unless a later step claims it (strip-chrome.py's
    slides player), so naming an edge in a step is emphasis, not required.
    """
    slides = spec.get("slides")
    if not slides or not isinstance(slides, list):
        return ["the page has no slides, so it cannot be told one step at a "
                "time; 4 to 6 steps, each adding the boxes and edges of one idea"]
    faults = []
    told: set[str] = set()
    for number, given in enumerate(slides, start=1):
        step = given if isinstance(given, dict) else {}
        if not step.get("label"):
            faults.append(f"slide {number} has no label saying what the step says")
        arriving = step.get("add")
        if not arriving or not isinstance(arriving, list):
            faults.append(f"slide {number} adds nothing")
            continue
        told |= {str(one) for one in arriving}
    boxes = _boxes(layout)
    edges = {f"{edge[0]}-{edge[1]}" for edge in _drawn_edges(layout)}
    for box in sorted(set(boxes) - told):
        faults.append(f"box '{box}' never appears in a step, so a reader being "
                      f"told the page never meets it")
    for ghost in sorted(told - set(boxes) - edges):
        faults.append(f"a step adds '{ghost}', which is neither a box nor an "
                      f"edge on this page")
    return faults


def _legend_faults(spec: dict, layout: dict) -> list[str]:
    """Name every kind the page draws; an unnamed edge renders as 'primary flow'."""
    nodes = _facts(spec)
    boxes = _boxes(layout)
    legend = spec.get("legend") if isinstance(spec.get("legend"), dict) else {}
    present = {nodes[box].get("type") for box in boxes if box in nodes}
    present |= {_edge_kind(edge) for edge in _drawn_edges(layout)}
    present.discard(None)
    faults = []
    for kind in sorted(present - set(legend)):
        drawn = "edge kind" if kind.startswith("edge-") else "box type"
        faults.append(f"the page draws the {drawn} '{kind}' and the legend does "
                      f"not name it, so it renders with archify's default wording")
    for key in sorted(set(legend) - set(LEGEND_ORDER)):
        faults.append(f"legend key '{key}' is not a kind archify knows, so the "
                      f"entry is dropped; the keys are {', '.join(LEGEND_ORDER)}")
    return faults


def _fit_faults(spec: dict, layout: dict) -> list[str]:
    """A label that runs out of its box, and a box that runs off the canvas."""
    nodes = _facts(spec)
    sizes = _sizes(layout)
    canvas = _pair(layout.get("canvas"))
    faults = [] if canvas else ["the canvas is not a [width, height]"]
    canvas = canvas or (0, 0)
    for box, position in sorted(_boxes(layout).items()):
        width, height = sizes[box]
        node = nodes.get(box) or {}
        label = str(node.get("label") or "")
        sublabel = str(node.get("sublabel") or "")
        if len(label) * LABEL_ADVANCE > width + FIT_SLACK:
            faults.append(f"the label '{label}' is about "
                          f"{round(len(label) * LABEL_ADVANCE)}px wide and box "
                          f"'{box}' is {width}px; shorten it or move the detail "
                          f"to the sublabel")
        if len(sublabel) * SUBLABEL_ADVANCE > width + FIT_SLACK:
            faults.append(f"the sublabel '{sublabel}' is about "
                          f"{round(len(sublabel) * SUBLABEL_ADVANCE)}px wide and "
                          f"box '{box}' is {width}px; 2 to 4 words fit")
        placed = _pair(position)
        if not placed:
            faults.append(f"box '{box}' is not placed at an [x, y]")
            continue
        left, top = placed
        if left < 0 or top < 0 or left + width > canvas[0] or top + height > canvas[1]:
            faults.append(f"box '{box}' sits outside the {canvas[0]}x{canvas[1]} "
                          f"canvas")
    return faults


def _legend_rows(spec: dict, layout: dict) -> int:
    """How many rows the legend wraps into at this canvas width."""
    nodes = _facts(spec)
    boxes = _boxes(layout)
    legend = spec.get("legend") if isinstance(spec.get("legend"), dict) else {}
    present = {nodes[box].get("type") for box in boxes if box in nodes}
    present |= {_edge_kind(edge) for edge in _drawn_edges(layout)}
    width = (_pair(layout.get("canvas")) or (0, 0))[0] - PAGE_MARGIN * 2
    rows, cursor, filled = 1, 0, False
    for kind in LEGEND_ORDER:
        if kind not in present or kind not in legend:
            continue
        swatch, gap = LEGEND_SWATCH["edge" if kind.startswith("edge-") else "node"]
        # a node kind carries the clickable badge, an edge kind does not
        badge = 0 if kind.startswith("edge-") else LEGEND_BADGE
        entry = math.ceil(swatch + gap
                          + len(str(legend[kind])) * LEGEND_FONT * LEGEND_ADVANCE
                          + badge)
        needed = (LEGEND_ITEM_GAP if filled else 0) + entry
        if filled and cursor + needed > width:
            rows, cursor = rows + 1, entry
        else:
            cursor, filled = cursor + needed, True
    return rows


def _room_faults(spec: dict, layout: dict) -> list[str]:
    """The legend needs the foot of the canvas; say so before the render does."""
    boxes = _boxes(layout)
    if not boxes:
        return ["the page has no boxes"]
    sizes = _sizes(layout)
    placed = {box: position for box in boxes
              if (position := _pair(boxes[box]))}
    if not placed:
        return []  # nothing is placed at all, which _fit_faults already said
    bottom = max(position[1] + sizes[box][1] for box, position in placed.items())
    for boundary in layout.get("boundaries") or []:
        members = [box for box in ((boundary or {}).get("wraps") or [])
                   if box in placed]
        if members:
            bottom = max(bottom, max(placed[box][1] + sizes[box][1]
                                     for box in members) + BOUNDARY_BOTTOM)
    needed = bottom + LEGEND_BAND + (_legend_rows(spec, layout) - 1) * LEGEND_ROW_GAP
    height = (_pair(layout.get("canvas")) or (0, 0))[1]
    if height < needed:
        return [f"the canvas is {height} tall and the legend needs it to be "
                f"{needed}: leave room under the lowest box, or the render "
                f"fails with legend/vertical-overflow"]
    return []


def page_faults(spec: dict, layout: dict) -> list[str]:
    """Every mechanical reason this page is not fit to be built, in plain words.

    Args:
        spec: the facts, as REDRAW-BRIEF.md describes them (title, subtitle,
            legend, nodes, slides).
        layout: the shape (canvas, boxes, sizes, boundaries, edges).

    Returns:
        A list of faults, empty when nothing mechanical is wrong. Each line
        names the box, edge or number at fault and what to do about it.
    """
    return (_placement_faults(spec, layout)
            + _story_faults(spec, layout)
            + _legend_faults(spec, layout)
            + _fit_faults(spec, layout)
            + _room_faults(spec, layout))
