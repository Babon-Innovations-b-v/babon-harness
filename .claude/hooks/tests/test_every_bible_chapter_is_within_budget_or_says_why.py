"""Every bible chapter is at or under its budget, or says in writing why not.

WHY. A bible can read well and still go stale, and the two facts share a
cause: once it is too much to re-read, nobody re-reads it when the code moves.
This is the overlay budget's twin, for the one file the overlay guard does not
cover.

WHAT IS CHECKED. Word count per ``## `` chapter against the budget in
``.claude/hooks/local/bible_guard.py``, which is the single definition of both the
number and what counts as a written reason, so the guard a session meets while
typing and the gate that judges the commit can never disagree. A chapter over
budget passes only if a line under its heading starts with ``Budget:``, plain,
bolded, or inside an HTML comment so the published page does not show it. The
reason itself is not graded here; a person reading the diff does that.

WHY A WRITTEN REASON RATHER THAN A LIST IN THIS FILE. A list of exempt
chapters here would be a second, worse index: it would go stale the way
everything else in this repository goes stale, and it would be invisible to the
person editing the chapter. The reason lives in the chapter, where whoever
grows it next has to read it.

The guard is loaded by path because ``.claude/hooks/`` is not an importable
package, and the bible is read from the tree rather than from git, because the
deploy gate runs this from an export of the commit.
"""

import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_BIBLE = _ROOT / "docs" / "bible.md"
_GUARD = _ROOT / ".claude" / "hooks" / "local" / "bible_guard.py"


def _guard():
    assert _GUARD.exists(), f"the guard that defines the budget is missing: {_GUARD}"
    spec = importlib.util.spec_from_file_location("bible_guard", _GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_bible_chapter_is_within_budget_or_says_why():
    guard = _guard()
    assert _BIBLE.exists(), f"there is no bible at {_BIBLE}"
    text = _BIBLE.read_text(encoding="utf-8")

    found = guard.chapters(text)
    assert len(found) >= 10, (
        f"only {len(found)} chapters parsed out of the bible; the heading shape moved")

    over = guard.over_budget(text)
    assert not over, (
        "these chapters are over the "
        f"flat budget of {guard.BUDGET_WORDS} words, with no written reason:\n"
        + "\n".join(f"  {name}: {words} words" for name, words in over)
        + "\n\nEither cut, or put a line starting 'Budget:' under the heading "
          "saying why the chapter earns more. An HTML comment keeps it off the "
          "published page."
    )


def test_the_chapter_ids_the_topic_table_points_at_all_exist():
    """Root CLAUDE.md routes every session to a chapter by id; a renamed
    heading breaks the topic table, the site split and every #anchor at once,
    and nothing else notices."""
    guard = _guard()
    names = set(guard.chapters(_BIBLE.read_text(encoding="utf-8")))
    table = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cited = {
        line.rsplit("| `", 1)[1].split("`")[0]
        for line in table.split("\n")
        if line.startswith("| ") and line.count("| `") == 1 and line.rstrip().endswith("` |")
    }
    unknown = {name for name in cited if "/" in name and name not in names}
    assert not unknown, (
        "root CLAUDE.md's topic table sends readers to chapters the bible does "
        f"not have: {sorted(unknown)}")


def test_every_bible_chapter_is_within_its_section_budget_or_says_why():
    """The sidebar is what a reader meets before a single sentence.

    A published page lists every ``### `` heading. A section is somewhere a
    reader navigates TO; a chapter
    that grows one per fact turns its own contents page into an index of parts.
    """
    guard = _guard()
    text = _BIBLE.read_text(encoding="utf-8")
    over = guard.over_sections(text)
    assert not over, (
        f"these chapters carry more than {guard.BUDGET_SECTIONS} sections with no "
        "written reason:\n"
        + "\n".join(f"  {name}: {sections} sections" for name, sections in over)
        + "\n\nMerge related sections under a heading that answers a question, or "
          "put a line starting 'Budget:' under the chapter heading saying why."
    )
