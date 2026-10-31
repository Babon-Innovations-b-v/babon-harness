"""bible_debt: what the bible still owes a page, in the words the spec used.

A box is explained by one sentence in a bible section, ending in the ◈ marker
that names the box. The spec that draws the page already proposes
that sentence in each node's ``bible`` field, so the sentence and the marker
can be handed back ready to paste: whoever writes the section is copying, not
composing from a box id.

Owns the debt, not the payment: it never edits ``docs/bible.md`` (the brief is
explicit that a page author does not), and it does not run the link map. What
is already claimed is read from the page's ``links.json``, which
``docs/diagrams/tools/linkmap.py`` writes.

FAILURE POLICY: read-only and quiet. A page with no sources drawn yet has no
debt to report and comes back empty; a box whose spec proposed no sentence
still comes back, with an empty ``sentence``, because a kept box keeps the
sentence it already had and only the marker needs checking.
"""
from __future__ import annotations

from runtime import MARKER_PREFIX, unclaimed_boxes


def _marker(page: str, box: str) -> str:
    """The ◈ link that makes a bible sentence claim one box on one page."""
    return f"[◈]({MARKER_PREFIX}stack/{page}.html#focus={box})"


def bible_debt(page: str, spec: dict | None = None,
               *, owing: list[str] | None = None) -> dict[str, dict[str, str]]:
    """The sentences the bible still owes this page, box by box.

    Args:
        page: the page slug, as passed to ``draw_module``.
        spec: the facts that drew it, so the sentence each node proposed comes
            back with its marker. Optional: without it only the markers do.
        owing: the boxes to report, for a caller that already worked them out
            or a test that has no page on disk. Defaults to the boxes the
            page's links.json does not claim.

    Returns:
        ``{box: {"sentence": proposed sentence, "marker": ◈ link, "line": the
        two joined}}`` for every box no bible sentence claims yet. Empty when
        the bible is square with the page.
    """
    nodes = (spec or {}).get("nodes") or {}
    owed = {}
    for box in (unclaimed_boxes(page) if owing is None else owing):
        sentence = str((nodes.get(box) or {}).get("bible") or "").strip()
        marker = _marker(page, box)
        owed[box] = {
            "sentence": sentence,
            "marker": marker,
            "line": f"{sentence} {marker}".strip(),
        }
    return owed
