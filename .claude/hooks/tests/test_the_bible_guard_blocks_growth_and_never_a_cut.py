"""The bible guard blocks a chapter growing past its budget, and never a cut.

WHY. Prose grows back because nothing pushes against it at the moment of
writing. ``.claude/hooks/local/bible_guard.py`` is
the standing answer, the same one ``overlay_guard.py`` gives for the overlays,
pointed at the one file that guard deliberately skips.

WHAT IS CHECKED. The guard's judgement, not the bible's current contents: that
it blocks a chapter grown past the flat 900-word budget with no written reason,
that it lets
a shrinking chapter through however heavy it still is, that a ``Budget:`` line
exempts a chapter whether it is plain, bolded or inside an HTML comment, that
it only ever judges the chapter an edit actually grew, and that anything it
cannot parse is allowed rather than refused. The separate question of whether
the committed bible is within budget is
``test_every_bible_chapter_is_within_budget_or_says_why.py``; this file would
still pass on a bloated tree, which is the point of keeping them apart.

The guard is loaded by path because ``.claude/hooks/`` is not an importable
package. If it is ever missing, the test says so rather than passing
vacuously.
"""

import importlib.util
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_GUARD = _ROOT / ".claude" / "hooks" / "local" / "bible_guard.py"


def _load():
    assert _GUARD.exists(), f"the guard this test is about is missing: {_GUARD}"
    spec = importlib.util.spec_from_file_location("bible_guard", _GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()


def _bible(*chapters: tuple[str, int]) -> str:
    """A bible with one chapter per (name, word count) pair."""
    out = []
    for name, words in chapters:
        out.append(f"## {name}")
        out.append(" ".join(["word"] * words))
    return "\n".join(out) + "\n"


def _decide(tmp_path, monkeypatch, current: str, tool: str, tool_input: dict) -> int:
    """Run the hook against a bible holding `current`, and return its exit code."""
    bible = tmp_path / "docs" / "bible.md"
    bible.parent.mkdir(parents=True, exist_ok=True)
    bible.write_text(current, encoding="utf-8")
    monkeypatch.setattr(guard, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO(json.dumps({
            "tool_name": tool,
            "tool_input": {"file_path": str(bible), **tool_input},
        })),
    )
    return guard.main()


#: Every chapter gets the same allowance, however many boxes it claims.
BUDGET = guard.BUDGET_WORDS


def test_a_chapter_grown_past_the_budget_is_blocked(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET + 1))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 2


def test_a_chapter_at_the_budget_is_allowed(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def test_a_shrinking_chapter_is_allowed_however_heavy_it_still_is(tmp_path, monkeypatch):
    """The cut is the point; a guard that fights the cutter is worse than none."""
    was = _bible(("infra/observability", 12_749))
    now = _bible(("infra/observability", 6_000))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def test_an_unchanged_over_budget_chapter_does_not_block_an_edit_elsewhere(tmp_path, monkeypatch):
    """Only the chapter an edit grows is judged, never the file as a whole."""
    was = _bible(("infra/platform", BUDGET + 500), ("apps/api", 100))
    now = _bible(("infra/platform", BUDGET + 500), ("apps/api", 300))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


@pytest.mark.parametrize("reason", [
    "Budget: 3,400 words; a reference table every chapter links to.",
    "**Budget:** a lookup table of service IDs, not prose.",
    "<!-- Budget: 2,200 words; a lookup table, not prose. -->",
])
def test_a_written_reason_exempts_the_chapter(tmp_path, monkeypatch, reason):
    was = _bible(("Identifiers", 100))
    now = f"## Identifiers\n{reason}\n" + " ".join(["word"] * (BUDGET + 1)) + "\n"
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def test_a_reason_under_one_chapter_does_not_excuse_another(tmp_path, monkeypatch):
    was = _bible(("Identifiers", 100), ("apps/api", 100))
    now = (
        "## Identifiers\n<!-- Budget: a lookup table. -->\n"
        + " ".join(["word"] * (BUDGET + 1))
        + "\n## apps/api\n"
        + " ".join(["word"] * (BUDGET + 1))
        + "\n"
    )
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 2


def test_an_edit_is_judged_on_what_it_would_leave_behind(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    padding = " ".join(["word"] * (BUDGET + 1))
    assert _decide(
        tmp_path, monkeypatch, was, "Edit",
        {"old_string": " ".join(["word"] * 100), "new_string": padding},
    ) == 2


def test_an_edit_whose_old_string_is_absent_is_left_to_the_tool(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    assert _decide(
        tmp_path, monkeypatch, was, "Edit",
        {"old_string": "text that is not in the file", "new_string": "x"},
    ) == 0


def test_a_file_that_is_not_the_bible_is_not_judged(tmp_path, monkeypatch):
    other = tmp_path / "docs" / "notes.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("## apps/api\nshort\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO(json.dumps({
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(other),
                "content": _bible(("apps/api", BUDGET + 1)),
            },
        })),
    )
    assert guard.main() == 0


def test_a_bible_outside_this_repository_is_not_judged(tmp_path, monkeypatch):
    """The path filter is repository-relative, so another checkout is not ours."""
    elsewhere = tmp_path / "elsewhere" / "docs" / "bible.md"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    elsewhere.write_text("## apps/api\nshort\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_REPO_ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO(json.dumps({
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(elsewhere),
                "content": _bible(("apps/api", BUDGET + 1)),
            },
        })),
    )
    assert guard.main() == 0


def test_it_fails_open_on_anything_it_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert guard.main() == 0


def test_the_env_switch_disarms_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_BIBLE_GUARD", "0")
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET + 1))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def test_drawing_more_boxes_buys_a_chapter_no_more_words():
    """A budget that grows per marker pays for drawing boxes, and a chapter
    fills it with one sentence per box until nobody can read it."""
    plain = "## apps/api\n" + " ".join(["word"] * 10)
    marker = "[◈](diagrams/stack/api.html#focus=door)"
    dense = "## infra/observability\n" + (f"text {marker} " * 500)
    assert guard.budget_for(plain) == guard.budget_for(dense) == guard.BUDGET_WORDS
    assert guard.over_budget(dense), (
        "a chapter is not allowed to outgrow the budget by carrying more markers")


def test_the_heading_line_never_counts_against_the_words_under_it():
    """A long chapter title is not prose the reader has to get through."""
    long_title = "## " + " ".join(["title"] * 50)
    text = long_title + "\n" + " ".join(["word"] * BUDGET) + "\n"
    assert guard.over_budget(text) == []
