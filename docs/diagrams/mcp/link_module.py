"""link_module tool: put a drawn page in front of a person.

A module map is drawn while the work happens and stays unlinked until the work
needs a human eye. This tool does that last step: it hangs the page off a box
on the stack or on a group page, so the module can be opened and discussed, and
it returns the address to paste into the issue or the review. A page with a box
that no bible sentence explains is not ready for a reader, so the link is
refused until that paragraph exists.

Linking moves two pages, not one. The parent gains the button that opens the
page, and the page itself gains the zoom-out button back to the parent, which
``strip-chrome.py`` works out from the parent's module map at patch time.
Patching only the parent would leave a freshly linked page with whatever way
back it had, and the link map would fail on it.

FAILURE POLICY: refuses rather than half-links. An unknown page or an unknown
parent box raises ValueError; unexplained boxes come back ``ok: false`` with
the sentences the bible owes and nothing is written. Once the parent's module
map is written both pages are patched and the link map runs; if either step
fails, ``ok`` is false and its output is in the return, and the set is left for
the next call to finish rather than rolled back. It never edits docs/bible.md
and never runs git: pushing is a person's decision.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib

from bible_debt import bible_debt
from runtime import (
    DATA,
    DIAGRAMS,
    LINKMAP,
    SITE,
    STACK,
    STRIP_CHROME,
    page_paths,
    run,
    unclaimed_boxes,
)

#: The byline baked into a delivered page, from config/harness.env.
AUTHORS = os.environ.get("DIAGRAM_AUTHORS", "Drawn with Claude")


def _patch_targets(page: pathlib.Path, parent: pathlib.Path) -> list[pathlib.Path]:
    """The pages a link changes: the page itself first, then its new parent.

    The page comes first because it is the one whose zoom-out button did not
    exist a moment ago; the parent only gains a button in a popup it already
    drew.
    """
    return [page, parent]


def link_module(name: str, parent_node: str, parent_page: str = "stack") -> dict:
    """Link a drawn module page to the box it belongs under.

    Args:
        name: the module slug passed to ``draw_module``.
        parent_node: the node id on the parent page that should carry the
            button, for example ``api`` on the stack.
        parent_page: ``stack`` for the top page, or a group page id such as
            ``group-apps``. Defaults to the stack.

    Returns:
        The address to share, or the reason it could not be linked.
    """
    paths = page_paths(name)
    if not paths["html"].exists():
        raise ValueError(f"no page for '{name}' yet; call draw_module first")

    # Showing a page to a person is the moment it has to be explainable, so a
    # box nobody wrote a paragraph for blocks the link.
    loose = unclaimed_boxes(name)
    if loose:
        return {
            "ok": False,
            "error": "some boxes have no bible sentence yet, so the page is not "
                     "ready for a reader",
            "unclaimed": loose,
            "bible_todo": bible_debt(name),
            "next": ("write those sentences into the right bible section, each "
                     "ending with its marker, run docs/diagrams/tools/linkmap.py, "
                     "then link again"),
        }

    # the sidecars of the parent page sit in data/, the page itself in the
    # served tree; both are addressed from the same parent-page name
    if parent_page == "stack":
        parent_data, parent_html_dir = DATA, DIAGRAMS
        href = f"stack/{name}.html"
    else:
        parent_data, parent_html_dir = paths["modules"].parent, STACK
        href = f"{name}.html"
    modules_path = parent_data / f"{parent_page}.modules.json"
    source = parent_data / f"{parent_page}.architecture.json"
    html = parent_html_dir / f"{parent_page}.html"
    if not source.exists():
        raise ValueError(f"unknown parent page '{parent_page}'")
    nodes = json.loads(source.read_text())
    ids = {node["id"] for node in (nodes.get("nodes") or nodes.get("components", []))}
    if parent_node not in ids:
        raise ValueError(f"'{parent_node}' is not a node on {parent_page}")

    modules = json.loads(modules_path.read_text()) if modules_path.exists() else {}
    modules[parent_node] = href
    modules_path.write_text(json.dumps(modules, indent=1, sort_keys=True) + "\n")

    today = datetime.date.today().isoformat()
    patched = [run(["python3", str(STRIP_CHROME), str(target), AUTHORS, today])
               for target in _patch_targets(paths["html"], html)]
    checked = run(["python3", str(LINKMAP)])
    return {
        "ok": all(step.returncode == 0 for step in patched) and checked.returncode == 0,
        "url": (f"{SITE}/diagrams/stack/{name}.html" if SITE
                else f"docs/diagrams/stack/{name}.html"),
        "linked_from": f"{parent_page}#focus={parent_node}",
        "patched": [(step.stdout or step.stderr).strip()[-120:] for step in patched],
        "linkmap": (checked.stdout or checked.stderr).strip()[-300:],
        "next": "push to main; the page is published with the next deploy",
    }
