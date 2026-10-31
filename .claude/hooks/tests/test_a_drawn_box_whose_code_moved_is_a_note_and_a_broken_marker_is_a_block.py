"""The diagram hook blocks what a machine can decide and reports what it cannot.

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
"""
from __future__ import annotations

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


def test_the_planted_set_is_clean_before_anything_is_broken(tree: Path) -> None:
    """Without this, both answers below could be about a broken plant."""
    done = _run(tree, tree / "docs/bible.md")
    assert done.returncode == 0, done.stderr


def test_a_marker_naming_a_box_that_does_not_exist_is_refused(tree: Path) -> None:
    """A machine can tell this is wrong, so the session is made to fix it."""
    bible = tree / "docs/bible.md"
    bible.write_text(bible.read_text(encoding="utf-8").replace(
        "#focus=gate)", "#focus=nosuchboxatall)"), encoding="utf-8")

    done = _run(tree, bible)
    assert done.returncode == 2, (
        f"a marker naming a box that does not exist did not block: {done.stderr}"
    )
    assert "nosuchboxatall" in done.stderr


def test_a_box_whose_code_moved_is_reported_and_the_edit_stands(tree: Path) -> None:
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


def test_the_hook_checks_the_tree_the_edited_file_is_in(tree: Path) -> None:
    """A worktree session must be told about its own tree, not another one."""
    bible = tree / "docs/bible.md"
    bible.write_text(bible.read_text(encoding="utf-8").replace(
        "#focus=gate)", "#focus=plantedinthecopy)"), encoding="utf-8")

    done = _run(tree, bible)
    assert "plantedinthecopy" in done.stderr, (
        "the hook did not see the fault planted in the tree holding the edited "
        f"file, so it read some other tree: {done.stderr}"
    )
