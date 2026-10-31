#!/usr/bin/env python3
"""PreToolUse guard: a bible chapter does not grow past its budget silently.

The rule (root CLAUDE.md): a bible chapter explains how a thing works to
someone who does not know it, and its length tracks what that reader needs,
never how much there is to say. Anything a reader would look up rather than
read is not prose; the repository index answers lookups. The budget is 900
words and 8 sections per chapter, flat; a chapter that genuinely earns more
says so in a line starting ``Budget:``.

WHY A GUARD AND NOT JUST A CUT. Prose grows back because nothing pushes
against it at the moment of writing. This is the same answer
``overlay_guard.py`` gives for the overlays, pointed at the one file the
overlay guard deliberately does not cover.

WHAT IT BLOCKS. A ``Write`` or ``Edit`` on ``docs/bible.md`` that leaves any
chapter over budget with MORE words than that chapter had, and no ``Budget:``
line under its heading. Shrinking a bloated chapter is always allowed, and so
is any edit that leaves every chapter at or under budget, so a session doing
the cutting is never in its way. Only chapters the edit actually grows are
judged: an edit to one chapter is never blocked by another chapter's weight.

THE EXEMPTION IS A WRITTEN REASON, NOT A LIST. A lookup table rather than
prose carries its reason in the file, where a reader sees it. On a published
site the reason is invisible, because it is written as an HTML comment:

    <!-- Budget: 2,200 words; a lookup table of service IDs, not prose. -->

FAILURE POLICY: fail-open. Any parse error, unknown shape or unrelated call
exits 0 (allow). Exit 2 + stderr is the only block path (the harness feeds
stderr back to the model as the block reason). ``HARNESS_BIBLE_GUARD=0``
disarms it, for a human at a terminal.
"""

import json
import os
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Words per chapter. Flat on purpose: a budget that grows with every box a
#: chapter's drawing holds pays for drawing boxes, and the chapter fills the
#: allowance with one sentence per box. The boxes are capped instead, at six a
#: page. The bible is the overview a person READS; the drawings carry the
#: mechanism, the overlays what an editor must not get wrong, the index every
#: lookup.
BUDGET_WORDS = 900


def budget_for(body: str) -> int:
    """This chapter's word budget. Flat, so drawing another box cannot raise it."""
    return BUDGET_WORDS

#: Sections per chapter. A published page lists every ``### `` heading in its
#: sidebar, so the count is what a reader meets before a single sentence. A
#: section is somewhere a reader navigates TO, not a slot for the next fact.
#: Same written exception as the words.
BUDGET_SECTIONS = 8

#: A line opening with "Budget:", optionally bolded or wrapped in an HTML
#: comment, is the written reason a chapter earns more than the budget. Its
#: presence anywhere under the chapter heading is the whole exemption.
_BUDGET_LINE = re.compile(r"^\s*(<!--\s*)?(\*\*)?budget:", re.IGNORECASE | re.MULTILINE)

_MESSAGE = (
    "Blocked: this would grow the bible chapter '{chapter}' to {new} words; the "
    f"budget is {BUDGET_WORDS} for every chapter (root CLAUDE.md).\n"
    "A chapter explains how a thing works to someone who does not know it, and "
    "its length tracks what that reader needs. Anything they would look up "
    "rather than read (paths, IDs, thresholds, command lines, per-file "
    "behaviour) is not prose; the index answers lookups.\n"
    "Either cut instead of adding, or, when the chapter genuinely earns more, "
    "put a line starting 'Budget:' under its heading saying why. An HTML "
    "comment keeps it off the published page. Shrinking is always allowed."
)

_SECTIONS_MESSAGE = (
    "Blocked: this would give the bible chapter '{chapter}' {new} sections; the "
    f"budget is {BUDGET_SECTIONS} (root CLAUDE.md).\n"
    "The published page lists every '### ' heading in its sidebar, so the count "
    "is what a reader meets before a single sentence. A section is somewhere "
    "they navigate TO, not a slot for the next fact; merge related ones under "
    "a heading that answers a question.\n"
    "Either merge, or put a line starting 'Budget:' under the chapter heading "
    "saying why. Removing sections is always allowed."
)


def _bible_path(raw: str) -> pathlib.Path | None:
    """The resolved path when `raw` is this repository's ``docs/bible.md``."""
    if not raw:
        return None
    candidate = pathlib.Path(str(raw).strip())
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return None
    if resolved.name != "bible.md" or resolved.parent.name != "docs":
        return None
    return resolved


def chapters(text: str) -> dict[str, str]:
    """Every ``## `` chapter in the bible, mapped to its body.

    The body is everything under the heading up to the next ``## ``, the
    heading line itself excluded, so a long title never counts against the
    words underneath it.
    """
    found: dict[str, str] = {}
    name = None
    body: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if name is not None:
                found[name] = "\n".join(body)
            name, body = line[3:].strip(), []
        elif name is not None:
            body.append(line)
    if name is not None:
        found[name] = "\n".join(body)
    return found


def over_budget(text: str, before: dict[str, int] | None = None) -> list[tuple[str, int]]:
    """Chapters over budget with no written reason, growing ones only.

    Args:
        text: the whole bible as it would be after the edit.
        before: word count per chapter as it was, or None to judge every
            chapter regardless of whether this edit grew it. The hook passes
            the counts; the invariant test passes None, because a chapter
            already over budget in a committed tree is a finding whoever grew
            it.
    """
    findings = []
    for name, body in chapters(text).items():
        words = len(body.split())
        if words <= budget_for(body):
            continue
        if before is not None and words <= before.get(name, 0):
            continue  # unchanged or shrinking: never in a cutter's way
        if _BUDGET_LINE.search(body):
            continue
        findings.append((name, words))
    return findings


def over_sections(text: str, before: dict[str, int] | None = None) -> list[tuple[str, int]]:
    """Chapters carrying more sections than the budget, with no written reason.

    The same shape as ``over_budget`` and for the same reason: a count a reader
    meets before any prose, capped, with the exception written where the next
    person to add a heading will read it.
    """
    findings = []
    for name, body in chapters(text).items():
        sections = sum(1 for line in body.split("\n") if line.startswith("### "))
        if sections <= BUDGET_SECTIONS:
            continue
        if before is not None and sections <= before.get(name, 0):
            continue
        if _BUDGET_LINE.search(body):
            continue
        findings.append((name, sections))
    return findings


def _section_counts(text: str) -> dict[str, int]:
    """Sections per chapter, as the guard counts them."""
    return {
        name: sum(1 for line in body.split("\n") if line.startswith("### "))
        for name, body in chapters(text).items()
    }


def _resulting_content(tool: str, tool_input: dict, current: str) -> str | None:
    """What the file would hold after the call, or None when that is unknowable."""
    if tool == "Write":
        return str(tool_input.get("content", ""))
    if tool == "Edit":
        old = str(tool_input.get("old_string", ""))
        new = str(tool_input.get("new_string", ""))
        if not old or old not in current:
            return None  # the tool itself will refuse; nothing to judge
        if tool_input.get("replace_all"):
            return current.replace(old, new)
        return current.replace(old, new, 1)
    return None


def main() -> int:
    if os.environ.get("HARNESS_BIBLE_GUARD", "1") == "0":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    bible = _bible_path(tool_input.get("file_path", ""))
    if bible is None:
        return 0

    try:
        current = bible.read_text(encoding="utf-8") if bible.exists() else ""
        result = _resulting_content(tool, tool_input, current)
        if result is None:
            return 0
        was = {name: len(body.split()) for name, body in chapters(current).items()}
        grown = over_budget(result, before=was)
        if grown:
            name, words = grown[0]
            print(
                _MESSAGE.format(
                    chapter=name,
                    new=words,
                    budget=budget_for(chapters(result).get(name, "")),
                ),
                file=sys.stderr,
            )
            return 2
        split = over_sections(result, before=_section_counts(current))
        if split:
            name, sections = split[0]
            print(_SECTIONS_MESSAGE.format(chapter=name, new=sections), file=sys.stderr)
            return 2
    except Exception:
        return 0  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
