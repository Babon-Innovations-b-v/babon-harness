"""check_diagrams tool: what is wrong with the drawn set right now, in one call.

The checking is not done here. ``docs/diagrams/tools/linkmap.py`` is the thing
that knows the set: it fails when a box is claimed by no bible sentence, by two,
or by a marker outside a section, when a page hangs off nothing, when
its back button lands where the reader could not have come from, and when
nothing clicks down to it. This tool runs it and hands back everything it said,
line by line, rather than keeping a second opinion about any of that.

What it adds is two things the checker cannot say. The first is a judgement:
which pages have become a redraw of the group page above them
(``group_echoes``). The second is the question a reviewer actually has, which
is whether a page is still true: ``page_freshness`` counts the commits that
landed on the code a box names since the page's facts last moved, so the
reading can go to the pages that changed instead of to all of them. Read its
coverage line first, because it speaks only for the pages whose author said
what they draw.

Both are reported and never failed on. A blocking check that is sometimes wrong
is a check people learn to route around.

FAILURE POLICY: read-only, and it reports rather than raises. A failing link
map is the answer, not an error: ``ok`` is false and every line the checker
printed comes back whole, untruncated, because a set with twenty problems is
exactly when a summary hides the one that matters. The duplicate hint never
touches ``ok``.
"""
from __future__ import annotations

from group_echoes import group_echoes
from page_freshness import page_freshness
from runtime import LINKMAP, STACK_DATA, run


def _pages() -> tuple[int, int]:
    """How many module pages and group pages the stack set has drawn."""
    drawn = {path.name[: -len(".architecture.json")]
             for path in STACK_DATA.glob("*.architecture.json")}
    groups = {page for page in drawn if page.startswith("group-")}
    return len(drawn - groups), len(groups)


def check_diagrams() -> dict:
    """Check the drawn set: run the link map, then say what a reader would say.

    Returns:
        Whether the set is whole, every line the link map printed (its problems
        and its own summary), the page counts, and any page that has become a
        redraw of its group. The last one is a hint for a human and is left out
        of ``ok`` on purpose.
    """
    if not LINKMAP.exists():
        return {"ok": False,
                "error": f"the link map is not at {LINKMAP}; find where "
                         f"linkmap.py moved to before trusting this answer"}
    checked = run(["python3", str(LINKMAP)])
    problems = [line.partition("linkmap: ")[2] or line
                for line in (checked.stderr or "").splitlines() if line.strip()]
    modules, groups = _pages()
    return {
        "ok": checked.returncode == 0,
        "problems": problems,
        "problem_count": len(problems),
        "linkmap_said": [line for line in (checked.stdout or "").splitlines()
                         if line.strip()],
        "module_pages": modules,
        "group_pages": groups,
        "pages_that_redraw_their_group": group_echoes(),
        "code_moved_since_the_page_did": page_freshness(),
    }
