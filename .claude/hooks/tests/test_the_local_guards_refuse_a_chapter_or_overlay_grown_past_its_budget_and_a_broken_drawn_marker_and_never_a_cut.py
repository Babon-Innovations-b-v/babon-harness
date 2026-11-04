"""The local guards refuse a chapter or an overlay grown past its budget, and a broken drawn marker, and never a cut.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

The diagram hook blocks what a machine can decide and reports what it cannot.

WHAT IT PINS. `linkmap_sync.py`'s two answers. A structural fault, a bible
marker naming a box that does not exist, is something the tool KNOWS is wrong,
so the edit is refused and the session fixes it. Drifted code, a box whose named
files have changed since somebody last read the drawing, is a question for a
person: does this picture still match? The hook prints that and lets the edit
stand.

WHY IT EXISTS. `drifted_code` fires on whoever edits the diagrams NEXT, about
commits they did not write. A check that refuses you for somebody else's change
is one you learn to scroll past, so drift is a note and only a structural fault
is a block.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A one-page
drawn set is planted in a scratch tree, beside a copy of the real tools, and the
hook is run against it as the harness runs it: a payload on stdin, an exit code
out. A tree whose bible marker names a box the drawing does not have is broken
however the hook feels about it, so it must refuse. A tree that is structurally
whole and merely has a box stamped against different bytes is a reading somebody
owes, not an error, so the edit must stand. Neither answer is read off the hook.

WHAT IT WAS PROVED AGAINST. The break makes every non-zero linkmap exit block
again, so the drift case is refused.

Every bible chapter is at or under its budget, or says in writing why not.

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

The bible guard blocks a chapter growing past its budget, and never a cut.

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
the committed bible is within budget is the chapter-budget cases; the guard
cases would still pass on a bloated tree, which is why both kinds are here.

The guard is loaded by path because ``.claude/hooks/`` is not an importable
package. If it is ever missing, the test says so rather than passing
vacuously.

The overlay guard blocks an overlay growing past 500 words, and never a cut.

WHAT IS CHECKED. The guard's judgement: a per-area ``CLAUDE.md`` grown past
the budget with no ``Budget:`` line is refused, a shrinking one is let through
however heavy it still is, a written reason exempts it, and the repository-root
``CLAUDE.md`` is project instructions and never judged.

The guard is loaded by path because ``.claude/hooks/`` is not an importable
package.
"""
from __future__ import annotations

import inspect


# From a drawn box whose code moved is a note and a broken marker is a block.

import json


import shutil


import subprocess


import sys


from pathlib import Path


import pytest


_REPO = Path(__file__).resolve().parents[3]


_HOOK = _REPO / ".claude/hooks/local/linkmap_sync.py"


_BIBLE = """# The book

## infra/deploy

### The gate

The gate runs the tests a commit can reach. [◈](diagrams/stack.html#focus=gate)
"""


def _plant(copy: Path, code_seen: str) -> None:
    """One drawn page, `stack`, with one box that names the code it draws."""
    data = copy / "docs/diagrams/data"
    specs = copy / "docs/diagrams/specs"
    data.mkdir(parents=True)
    specs.mkdir(parents=True)
    (copy / "infra").mkdir()
    (copy / "infra/gate.sh").write_text("echo gate\n", encoding="utf-8")
    (data / "stack.architecture.json").write_text(json.dumps({
        "meta": {"title": "The stack"},
        "components": [{"id": "gate", "label": "Gate"}],
    }), encoding="utf-8")
    (data / "stack.code.json").write_text(json.dumps({"gate": ["infra/gate.sh"]}),
                                          encoding="utf-8")
    (specs / "stack.json").write_text(json.dumps({
        "title": "The stack",
        "nodes": {"gate": {"label": "Gate", "code_seen": code_seen}},
    }), encoding="utf-8")
    (copy / "docs/bible.md").write_text(_BIBLE, encoding="utf-8")


def _stamp(copy: Path) -> str:
    """The fingerprint linkmap itself records for the planted box."""
    done = subprocess.run(
        [sys.executable, "docs/diagrams/tools/linkmap.py", "--restamp", "stack#gate"],
        cwd=copy, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(copy)},
    )
    assert "restamped 1" in done.stdout, done.stdout + done.stderr
    return json.loads((copy / "docs/diagrams/specs/stack.json").read_text())["nodes"]["gate"]["code_seen"]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """The real tools beside a planted page, so a plant cannot touch the real set."""
    copy = tmp_path / "repo"
    shutil.copytree(_REPO / "docs/diagrams/tools", copy / "docs/diagrams/tools")
    _plant(copy, code_seen="0" * 12)
    _stamp(copy)
    return copy


def _run(tree: Path, edited: Path) -> subprocess.CompletedProcess[str]:
    """Run the hook the way the harness does: a payload on stdin."""
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"tool_input": {"file_path": str(edited)}}),
        capture_output=True,
        text=True,
        timeout=120,
        # Empty, so a fallback to the real checkout would be visible as a pass
        # for the wrong reason rather than hidden by the environment.
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tree)},
    )


def _the_planted_set_is_clean_before_anything_is_broken(tree: Path) -> None:
    """Without this, both answers below could be about a broken plant."""
    done = _run(tree, tree / "docs/bible.md")
    assert done.returncode == 0, done.stderr


def _a_marker_naming_a_box_that_does_not_exist_is_refused(tree: Path) -> None:
    """A machine can tell this is wrong, so the session is made to fix it."""
    bible = tree / "docs/bible.md"
    bible.write_text(bible.read_text(encoding="utf-8").replace(
        "#focus=gate)", "#focus=nosuchboxatall)"), encoding="utf-8")

    done = _run(tree, bible)
    assert done.returncode == 2, (
        f"a marker naming a box that does not exist did not block: {done.stderr}"
    )
    assert "nosuchboxatall" in done.stderr


def _a_box_whose_code_moved_is_reported_and_the_edit_stands(tree: Path) -> None:
    """A person has to answer this one, so the hook asks rather than refuses."""
    (tree / "infra/gate.sh").write_text("echo gate, changed\n", encoding="utf-8")
    spec = tree / "docs/diagrams/specs/stack.json"

    done = _run(tree, spec)
    assert done.returncode == 0, (
        "a drawn box whose code moved refused the edit; that is a reading "
        f"somebody owes, not a fault the hook can decide: {done.stderr}"
    )
    assert "moved" in done.stderr, (
        f"the drift was not reported at all, so nobody is asked to read it: {done.stderr!r}"
    )


def _the_hook_checks_the_tree_the_edited_file_is_in(tree: Path) -> None:
    """A worktree session must be told about its own tree, not another one."""
    bible = tree / "docs/bible.md"
    bible.write_text(bible.read_text(encoding="utf-8").replace(
        "#focus=gate)", "#focus=plantedinthecopy)"), encoding="utf-8")

    done = _run(tree, bible)
    assert "plantedinthecopy" in done.stderr, (
        "the hook did not see the fault planted in the tree holding the edited "
        f"file, so it read some other tree: {done.stderr}"
    )

# From every bible chapter is within budget or says why.

import importlib.util


import pathlib


_ROOT = pathlib.Path(__file__).resolve().parents[3]


_BIBLE_2 = _ROOT / "docs" / "bible.md"


_GUARD = _ROOT / ".claude" / "hooks" / "local" / "bible_guard.py"


def _guard():
    assert _GUARD.exists(), f"the guard that defines the budget is missing: {_GUARD}"
    spec = importlib.util.spec_from_file_location("bible_guard", _GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _every_bible_chapter_is_within_budget_or_says_why():
    guard = _guard()
    assert _BIBLE_2.exists(), f"there is no bible at {_BIBLE_2}"
    text = _BIBLE_2.read_text(encoding="utf-8")

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


def _the_chapter_ids_the_topic_table_points_at_all_exist():
    """Root CLAUDE.md routes every session to a chapter by id; a renamed
    heading breaks the topic table, the site split and every #anchor at once,
    and nothing else notices."""
    guard = _guard()
    names = set(guard.chapters(_BIBLE_2.read_text(encoding="utf-8")))
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


def _every_bible_chapter_is_within_its_section_budget_or_says_why():
    """The sidebar is what a reader meets before a single sentence.

    A published page lists every ``### `` heading. A section is somewhere a
    reader navigates TO; a chapter
    that grows one per fact turns its own contents page into an index of parts.
    """
    guard = _guard()
    text = _BIBLE_2.read_text(encoding="utf-8")
    over = guard.over_sections(text)
    assert not over, (
        f"these chapters carry more than {guard.BUDGET_SECTIONS} sections with no "
        "written reason:\n"
        + "\n".join(f"  {name}: {sections} sections" for name, sections in over)
        + "\n\nMerge related sections under a heading that answers a question, or "
          "put a line starting 'Budget:' under the chapter heading saying why."
    )

# From the bible guard blocks growth and never a cut.

import io


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


def _a_chapter_grown_past_the_budget_is_blocked(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET + 1))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 2


def _a_chapter_at_the_budget_is_allowed(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def _a_shrinking_chapter_is_allowed_however_heavy_it_still_is(tmp_path, monkeypatch):
    """The cut is the point; a guard that fights the cutter is worse than none."""
    was = _bible(("infra/observability", 12_749))
    now = _bible(("infra/observability", 6_000))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def _an_unchanged_over_budget_chapter_does_not_block_an_edit_elsewhere(tmp_path, monkeypatch):
    """Only the chapter an edit grows is judged, never the file as a whole."""
    was = _bible(("infra/platform", BUDGET + 500), ("apps/api", 100))
    now = _bible(("infra/platform", BUDGET + 500), ("apps/api", 300))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def _a_written_reason_exempts_the_chapter(tmp_path, monkeypatch, reason):
    was = _bible(("Identifiers", 100))
    now = f"## Identifiers\n{reason}\n" + " ".join(["word"] * (BUDGET + 1)) + "\n"
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def _a_reason_under_one_chapter_does_not_excuse_another(tmp_path, monkeypatch):
    was = _bible(("Identifiers", 100), ("apps/api", 100))
    now = (
        "## Identifiers\n<!-- Budget: a lookup table. -->\n"
        + " ".join(["word"] * (BUDGET + 1))
        + "\n## apps/api\n"
        + " ".join(["word"] * (BUDGET + 1))
        + "\n"
    )
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 2


def _an_edit_is_judged_on_what_it_would_leave_behind(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    padding = " ".join(["word"] * (BUDGET + 1))
    assert _decide(
        tmp_path, monkeypatch, was, "Edit",
        {"old_string": " ".join(["word"] * 100), "new_string": padding},
    ) == 2


def _an_edit_whose_old_string_is_absent_is_left_to_the_tool(tmp_path, monkeypatch):
    was = _bible(("apps/api", 100))
    assert _decide(
        tmp_path, monkeypatch, was, "Edit",
        {"old_string": "text that is not in the file", "new_string": "x"},
    ) == 0


def _a_file_that_is_not_the_bible_is_not_judged(tmp_path, monkeypatch):
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


def _a_bible_outside_this_repository_is_not_judged(tmp_path, monkeypatch):
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


def _it_fails_open_on_anything_it_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert guard.main() == 0


def _the_env_switch_disarms_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_BIBLE_GUARD", "0")
    was = _bible(("apps/api", 100))
    now = _bible(("apps/api", BUDGET + 1))
    assert _decide(tmp_path, monkeypatch, was, "Write", {"content": now}) == 0


def _drawing_more_boxes_buys_a_chapter_no_more_words():
    """A budget that grows per marker pays for drawing boxes, and a chapter
    fills it with one sentence per box until nobody can read it."""
    plain = "## apps/api\n" + " ".join(["word"] * 10)
    marker = "[◈](diagrams/stack/api.html#focus=door)"
    dense = "## infra/observability\n" + (f"text {marker} " * 500)
    assert guard.budget_for(plain) == guard.budget_for(dense) == guard.BUDGET_WORDS
    assert guard.over_budget(dense), (
        "a chapter is not allowed to outgrow the budget by carrying more markers")


def _the_heading_line_never_counts_against_the_words_under_it():
    """A long chapter title is not prose the reader has to get through."""
    long_title = "## " + " ".join(["title"] * 50)
    text = long_title + "\n" + " ".join(["word"] * BUDGET) + "\n"
    assert guard.over_budget(text) == []

# From the overlay guard blocks growth and never a cut.

_GUARD_4 = _ROOT / ".claude" / "hooks" / "local" / "overlay_guard.py"


def _load_4():
    assert _GUARD_4.exists(), f"the guard this test is about is missing: {_GUARD_4}"
    spec = importlib.util.spec_from_file_location("overlay_guard", _GUARD_4)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard_4 = _load_4()


BUDGET_4 = guard_4.BUDGET_WORDS


def _decide_4(tmp_path, monkeypatch, relative: str, current: str, content: str) -> int:
    overlay = tmp_path / relative
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(current, encoding="utf-8")
    monkeypatch.setattr(guard_4, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": str(overlay), "content": content},
    })))
    return guard_4.main()


def _words(count: int) -> str:
    return " ".join(["word"] * count) + "\n"


def _an_overlay_grown_past_the_budget_is_blocked(tmp_path, monkeypatch):
    assert _decide_4(tmp_path, monkeypatch, "apps/x/CLAUDE.md", _words(10), _words(BUDGET_4 + 1)) == 2


def _a_shrinking_overlay_is_allowed_however_heavy_it_still_is(tmp_path, monkeypatch):
    assert _decide_4(tmp_path, monkeypatch, "apps/x/CLAUDE.md",
                   _words(BUDGET_4 * 3), _words(BUDGET_4 * 2)) == 0


def _a_budget_line_exempts_the_overlay(tmp_path, monkeypatch):
    content = "Budget: 900 words; every command here is load-bearing.\n" + _words(BUDGET_4 + 1)
    assert _decide_4(tmp_path, monkeypatch, "apps/x/CLAUDE.md", _words(10), content) == 0


def _the_root_file_is_not_an_overlay(tmp_path, monkeypatch):
    assert _decide_4(tmp_path, monkeypatch, "CLAUDE.md", _words(10), _words(BUDGET_4 + 1)) == 0


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_the_planted_set_is_clean_before_anything_is_broken),
    *_cases(_a_marker_naming_a_box_that_does_not_exist_is_refused),
    *_cases(_a_box_whose_code_moved_is_reported_and_the_edit_stands),
    *_cases(_the_hook_checks_the_tree_the_edited_file_is_in),
    *_cases(_every_bible_chapter_is_within_budget_or_says_why),
    *_cases(_the_chapter_ids_the_topic_table_points_at_all_exist),
    *_cases(_every_bible_chapter_is_within_its_section_budget_or_says_why),
    *_cases(_a_chapter_grown_past_the_budget_is_blocked),
    *_cases(_a_chapter_at_the_budget_is_allowed),
    *_cases(_a_shrinking_chapter_is_allowed_however_heavy_it_still_is),
    *_cases(_an_unchanged_over_budget_chapter_does_not_block_an_edit_elsewhere),
    *_cases(_a_written_reason_exempts_the_chapter, "reason", [
    "Budget: 3,400 words; a reference table every chapter links to.",
    "**Budget:** a lookup table of service IDs, not prose.",
    "<!-- Budget: 2,200 words; a lookup table, not prose. -->",
]),
    *_cases(_a_reason_under_one_chapter_does_not_excuse_another),
    *_cases(_an_edit_is_judged_on_what_it_would_leave_behind),
    *_cases(_an_edit_whose_old_string_is_absent_is_left_to_the_tool),
    *_cases(_a_file_that_is_not_the_bible_is_not_judged),
    *_cases(_a_bible_outside_this_repository_is_not_judged),
    *_cases(_it_fails_open_on_anything_it_cannot_read),
    *_cases(_the_env_switch_disarms_it),
    *_cases(_drawing_more_boxes_buys_a_chapter_no_more_words),
    *_cases(_the_heading_line_never_counts_against_the_words_under_it),
    *_cases(_an_overlay_grown_past_the_budget_is_blocked),
    *_cases(_a_shrinking_overlay_is_allowed_however_heavy_it_still_is),
    *_cases(_a_budget_line_exempts_the_overlay),
    *_cases(_the_root_file_is_not_an_overlay),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_local_guards_refuse_a_chapter_or_overlay_grown_past_its_budget_and_a_broken_drawn_marker_and_never_a_cut(scenario, given, uses, request):
    """The local guards refuse a chapter or an overlay grown past its budget, and a broken drawn marker, and never a cut: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
