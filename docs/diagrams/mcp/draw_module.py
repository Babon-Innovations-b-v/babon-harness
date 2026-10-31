"""draw_module tool: turn a story spec into a served diagram page.

The caller supplies two things: the facts (boxes with their popup text, the
legend, the slides that tell the page one step at a time) and the shape (where
each box sits, which regions wrap them, which edges run between them). Routing,
validation, delivery and popup wiring happen here, so one call replaces the
whole archify sequence.

A page that would embarrass its author is refused before anything is written:
no slides, a box no step ever adds, an edge kind the legend does not name, a
label too wide for its box, a canvas with no room for the legend. The reasons
come from ``page_faults``. The page is written but never linked: linking is a
separate, deliberate step, and it is refused until every box on the page is
explained by a bible sentence, so the return here lists
what the bible still owes, in the words the spec proposed.

FAILURE POLICY: refuses before it writes. A malformed call raises ValueError
(the caller is a program and got the shape wrong); a page with faults comes
back ``ok: false`` with every reason at once and nothing on disk, so a half
page is never left in the specs directory for the next agent to find. A build
that fails after the spec is written comes back ``ok: false`` with the tail of
the build log, and the spec stays, because it is the thing being fixed. It
never links, never touches docs/bible.md and never runs git.
"""
from __future__ import annotations

from bible_debt import bible_debt
from page_faults import page_faults
from runtime import BUILD_FREE, page_paths, run, write_spec


def draw_module(name: str, spec: dict, layout: dict) -> dict:
    """Draw one module as a page in the house style.

    Args:
        name: short slug for the module, for example ``deploy`` or
            ``notulen``; a page that gathers several modules carries the
            ``group-`` prefix, as in ``group-apps``. ``stack`` draws the top
            page itself. The page is written to
            ``docs/diagrams/stack/<name>.html``, and its kind label follows
            from where it sits, so a group page says layer and a module page
            says module without anyone writing it.
        spec: the facts. Required keys: ``title``, ``subtitle``, ``legend``,
            ``nodes`` (6 to 10 entries, each with type, label, sublabel, note,
            the bible sentence that claims it, an optional module link, and an
            optional ``code`` list naming the files or directories the box
            draws; write that while you draw, because nothing can work it out
            afterwards),
            and ``slides``: 4 to 6 steps that add the boxes and edges of one
            idea each, so the page can be told rather than only shown.
        layout: the shape. Required keys: ``canvas`` and ``boxes`` (top-left
            corners) and ``edges``. Optional: ``sizes``, ``boundaries``.
            The design system both files follow, including the shape rules and
            the legend keys, is ``docs/diagrams/tools/REDRAW-BRIEF.md``.

    Returns:
        Where the page landed, how many boxes and edges it holds, and the
        bible sentences its new boxes still owe. On a refusal, every reason.
    """
    if not name or "/" in name:
        raise ValueError("name must be a plain slug, no slashes")
    for key in ("title", "subtitle", "legend", "nodes"):
        if key not in spec:
            raise ValueError(f"spec is missing '{key}'; see REDRAW-BRIEF.md")
    for key in ("canvas", "boxes", "edges"):
        if key not in layout:
            raise ValueError(f"layout is missing '{key}'; see REDRAW-BRIEF.md")

    faults = page_faults(spec, layout)
    if faults:
        return {
            "ok": False,
            "name": name,
            "error": "the page was not drawn; it would have to be caught by a "
                     "human later",
            "faults": faults,
            "next": "fix these in the spec and the layout and call again; the "
                    "rules behind them are docs/diagrams/tools/REDRAW-BRIEF.md",
        }
    if not BUILD_FREE.exists():
        return {
            "ok": False,
            "name": name,
            "error": f"the builder is not at {BUILD_FREE}; find where "
                     f"build_free.py moved to before drawing anything",
        }

    write_spec(name, spec, layout)
    built = run(["python3", str(BUILD_FREE), name if name == "stack" else f"stack/{name}"])
    paths = page_paths(name)
    if built.returncode != 0 or not paths["html"].exists():
        return {
            "ok": False,
            "name": name,
            "error": "the page did not build",
            "detail": (built.stdout + built.stderr)[-1500:],
        }
    owed = bible_debt(name, spec)
    return {
        "ok": True,
        "name": name,
        "page": str(paths["html"].relative_to(paths["html"].parents[3])),
        "nodes": len(spec["nodes"]),
        "edges": len(layout["edges"]),
        "slides": len(spec.get("slides") or []),
        "linked": False,
        "bible_todo": owed,
        "next": (
            "write the bible section for this module, each sentence above ending "
            "in its marker, then run docs/diagrams/tools/linkmap.py; the page "
            "stays linked to nothing until the work needs a human eye"
            if owed else
            "every box has its bible sentence; link the page when the work needs "
            "a human eye"
        ),
    }
