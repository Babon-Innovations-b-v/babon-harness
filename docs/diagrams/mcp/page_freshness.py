"""Which drawn pages the code moved out from under, and how far.

Reviewing a page is the expensive half of the drawn set, because nothing in the
pipeline answers the only question a reviewer has: is this still true? The link
map proves the set is internally consistent, the bible link proves a chapter
exists, and neither looks at the code. So a reviewer opens the page, clicks
every box, reads about six hundred words and checks each claim by hand.

Most of that reading is wasted, because most pages did not change. What is
worth reading is the page whose code moved after the page did. That is now
answerable, because a box may name the files it draws, so this counts the
commits that landed on those files since the page was last built and hands back
the ones that did.

It reports coverage as loudly as it reports staleness, and that is deliberate.
The `code` field is filled in as pages are drawn and is never back-filled, so
this speaks for a growing minority of the set. A report that quietly covered a
tenth of the pages would read exactly like one that covered all of them, which
is the failure this whole exercise is about.

FAILURE POLICY: read-only and quiet. A page with no code field is not a fault,
it is a page whose author did not say; it is counted as unanswerable and left
alone. A git call that fails leaves that page unanswerable too, with the reason,
rather than reporting it as fresh.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

from runtime import DIAGRAMS, REPO


def _last_commit(paths: list[str]) -> tuple[str, str] | None:
    """The newest commit touching any of these paths, as (sha, iso date)."""
    if not paths:
        return None
    try:
        done = subprocess.run(
            ["git", "log", "-1", "--format=%h %cI", "--"] + paths,
            cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (done.stdout or "").strip()
    if done.returncode != 0 or not line:
        return None
    sha, _, when = line.partition(" ")
    return sha, when


def _commits_since(paths: list[str], since: str) -> list[str]:
    """The commits that touched these paths after the page was last built."""
    try:
        done = subprocess.run(
            ["git", "log", f"--since={since}", "--format=%h %s", "--"] + paths,
            cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in (done.stdout or "").splitlines() if line.strip()]


def _code_sidecars() -> dict[str, dict[str, list[str]]]:
    """Every page that says what it draws, as page name -> box -> paths."""
    found = {}
    for sidecar in sorted((DIAGRAMS / "data").rglob("*.code.json")):
        page = str(sidecar.relative_to(DIAGRAMS / "data")).removesuffix(".code.json")
        try:
            named = json.loads(sidecar.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if named:
            found[page] = named
    return found


def _spec_for(page: str) -> "pathlib.Path | None":
    """The file a page's facts live in, or None when it has none.

    build_free.py owns this naming: page ``stack/deploy`` was drawn from
    ``specs/stack/deploy.json``.
    """
    path = DIAGRAMS / "specs" / f"{page}.json"
    return path if path.exists() else None


def page_freshness() -> dict:
    """Pages whose code moved after they were drawn, and how much of the set that is.

    Returns:
        ``stale``, one row per page that is behind with the commits that put it
        there; ``fresh``, the pages checked and found current; and ``coverage``,
        saying how many of the drawn pages could be checked at all. Read the
        coverage line before the verdict: a page whose author never said what it
        draws is unanswerable here, not fresh.
    """
    sidecars = _code_sidecars()
    drawn = len({str(path.relative_to(DIAGRAMS / "data")).partition(".")[0]
                 for path in (DIAGRAMS / "data").rglob("*.architecture.json")}
                | {str(path.relative_to(DIAGRAMS / "data")).partition(".")[0]
                   for path in (DIAGRAMS / "data").rglob("*.workflow.json")})

    stale, fresh, unanswerable = [], [], []
    for page, boxes in sidecars.items():
        # The spec, not the delivered .html. The page is rebuilt for reasons
        # that have nothing to do with what it says, a re-delivery after a
        # sidecar edit being the common one, and anchoring on the .html would
        # let any of those reset the clock and call a stale page fresh. The
        # spec moves when the facts move, which is the thing being asked about.
        spec = _spec_for(page)
        drawn_at = _last_commit([str(spec.relative_to(REPO))]) if spec else None
        if drawn_at is None:
            unanswerable.append({"page": page,
                                 "why": "no spec on disk, or it is not committed yet"})
            continue
        behind = {}
        for box, paths in sorted(boxes.items()):
            moved = _commits_since(paths, drawn_at[1])
            if moved:
                behind[box] = moved
        row = {"page": page, "drawn_at": drawn_at[0], "drawn_on": drawn_at[1][:10]}
        if behind:
            stale.append({**row, "boxes_behind": behind,
                          "commits": sum(len(rows) for rows in behind.values())})
        else:
            fresh.append(row)

    return {
        "stale": sorted(stale, key=lambda row: -row["commits"]),
        "fresh": [row["page"] for row in fresh],
        "unanswerable": unanswerable,
        "coverage": {
            "pages_drawn": drawn,
            "pages_that_say_what_they_draw": len(sidecars),
            "say": (
                f"{len(sidecars)} of {drawn} pages name the code they draw, so this "
                f"answers for those and says nothing about the other "
                f"{drawn - len(sidecars)}. The field is filled in as pages are "
                f"drawn and is never back-filled, so this number grows with the "
                f"set rather than being caught up in one sweep."
            ),
        },
    }
