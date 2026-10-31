"""group_echoes: which pages have become a redraw of the group page above them.

A group page draws one layer of the stack and a module page under it answers
one question about one service, so the two should read differently. When they
stop reading differently one of them has stopped saying anything, and no
mechanical check catches it: the link map is happy, every box is claimed, the
page builds.

The signal is deliberately cheap: the words in the labels and sublabels of one
page against the words of its group, the box ids they share, and how many
boxes each holds. It is a hint for a reader, never a verdict, so nothing here
fails on it.

FAILURE POLICY: read-only, and it never raises for a set in flux. A group with
no drawn source, a module link pointing at a page that is not drawn yet, and a
sidecar that is being rewritten as it is read are all skipped rather than
reported: the checker owns "something is missing", this owns "these two read
the same".

Threshold: on a set of about a hundred pages the word overlap between a module
page and its group ran to a median of 0.21 and a 90th percentile of 0.28. Half
the words in common is well past anything a set does by accident.
"""
from __future__ import annotations

import json
import pathlib
import re

from runtime import STACK_DATA

ECHO = 0.5
# Short words carry no signal: "the", "a", "per" match everywhere.
WORD = re.compile(r"[a-z0-9]{3,}")


def _boxes(folder: pathlib.Path, page: str) -> tuple[set[str], set[str]]:
    """The ids a page draws and the words it says on them, or two empty sets."""
    source = folder / f"{page}.architecture.json"
    if not source.exists():
        return set(), set()
    try:
        components = json.loads(source.read_text()).get("components") or []
    except (json.JSONDecodeError, OSError):
        return set(), set()
    words: set[str] = set()
    for box in components:
        words |= set(WORD.findall(
            f"{box.get('label', '')} {box.get('sublabel', '')}".lower()))
    return {box["id"] for box in components}, words


def group_echoes(folder: pathlib.Path | None = None) -> dict[str, str]:
    """Module pages that read like the group page that opens them.

    Args:
        folder: where the built sources and module maps sit. Defaults to the
            stack set's data directory; a caller passing another one is a test.

    Returns:
        ``{page: one line of numbers}`` for every page over the threshold, so a
        human can open the two and decide. Empty when the set reads cleanly.
    """
    folder = folder or STACK_DATA
    echoes = {}
    for path in sorted(folder.glob("group-*.modules.json")):
        group = path.name[: -len(".modules.json")]
        above_ids, above_words = _boxes(folder, group)
        if not above_words:
            continue
        try:
            links = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for href in links.values():
            page = href.split("#")[0].split("/")[-1].removesuffix(".html")
            if page == group:
                continue
            ids, words = _boxes(folder, page)
            if not words:
                continue
            shared_words = len(words & above_words) / len(words)
            if shared_words < ECHO:
                continue
            echoes[page] = (
                f"{round(100 * shared_words)}% of its words and "
                f"{len(ids & above_ids)} of its {len(ids)} box ids are also on "
                f"{group}, which draws {len(above_ids)}; read both and decide "
                f"which one is still saying something")
    return echoes
