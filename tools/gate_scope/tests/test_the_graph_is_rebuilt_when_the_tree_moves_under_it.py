"""A remembered answer is only reused for the tree it was built from.

WHAT IT PINS. The memory in `_graph.build` and `_floor.derive`. Both are pure
functions of the tree and both are expensive, so an answer is remembered,
keyed on a hash of every first-party source's content.

WHY THIS TEST AND NOT THE SPEED. Speed is the reason the memory exists and it is
not the risk. The risk is a gate selecting against a tree that has since changed,
which is the one direction this package may not fail in: a scope narrower than
the change deserves is a green gate on code nobody ran. So this file asks the
only question that matters about a remembered answer, which is whether it is let
go of.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three trees are
built here whose right answers follow from the import edges this file writes,
never from what the selector said a moment earlier. An edge is added, so a suite
that could not break now can. The edge is then repointed at a package whose name
is the same length, so the two versions of the file are the same size; a key of
`(mtime_ns, size)` would see no change when two writes land inside one
filesystem tick. And a file is deleted, which
touches no other file at all.

WHAT IT WAS PROVED AGAINST. The break drops the stamp from the graph's key, so a
tree's path alone decides, and every second answer is the first one again.

GUARDS. The selector's memory.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools.gate_scope import _graph
from tools.gate_scope.select import GATE_STEP, decide

#: The two leaves. Separate top-level packages, because the selector answers at
#: directory granularity and two modules in one package cannot be told apart in
#: its answer. Their names are the SAME LENGTH, which is what makes the
#: byte-count case below possible.
_LEAF = "def value() -> int:\n    return 50\n"
_LEAF_TEST = (
    "from {package}.value import value\n\n\n"
    "def test_value() -> None:\n    assert value() == 50\n"
)

#: A tree where `report` imports neither leaf, so changing a leaf can only
#: break that leaf's own suite.
_TREE = {
    "readings/__init__.py": "",
    "readings/value.py": _LEAF,
    "readings/tests/__init__.py": "",
    "readings/tests/test_value.py": _LEAF_TEST.format(package="readings"),
    "readouts/__init__.py": "",
    "readouts/value.py": _LEAF,
    "readouts/tests/__init__.py": "",
    "readouts/tests/test_value.py": _LEAF_TEST.format(package="readouts"),
    "report/__init__.py": "",
    "report/headline.py": "def headline() -> str:\n    return 'steady'\n",
    "report/tests/__init__.py": "",
    "report/tests/test_headline.py": (
        "from report.headline import headline\n\n\n"
        "def test_headline() -> None:\n    assert headline() == 'steady'\n"
    ),
    # The selector reads the gate's own ignore list and answers `full` without
    # it, which would make every assertion here pass for the wrong reason.
    GATE_STEP: "#!/usr/bin/env bash\npytest -q --ignore=vendored\n",
}


def _headline_importing(package: str) -> str:
    """`report/headline.py` written to import one named leaf.

    `readings` and `readouts` are the same length, so the two versions of this
    file are the same size and a stamp counting only bytes would call them one
    tree.
    """
    return (
        f"from {package}.value import value\n\n\n"
        "def headline() -> str:\n    return 'steady' if value() else 'flat'\n"
    )


def _tree(root: Path) -> Path:
    """Write the tree and put it under git, which is what the selector asks."""
    for relative, source in _TREE.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _rewrite(repo: Path, relative: str, source: str) -> None:
    """Change one file and tell git, the way an ordinary edit would."""
    (repo / relative).write_text(source, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)


def _selects(repo: Path, changed: str, test: str) -> bool:
    """Would the gate run `test` for a change to `changed`?

    `decide` answers with the directories it would hand pytest, so containment
    is what "selected" means.
    """
    decision = decide([changed], repo)
    return any(
        test == path or test.startswith(path.rstrip("/") + "/")
        for path in decision.paths
    )


def test_an_import_added_since_the_last_question_is_seen(tmp_path: Path) -> None:
    """The tree grows an edge between two questions, so the answer must grow.

    Before, `readings` is a stranger to the report and only its own suite can
    break. After, the report imports it. A selector answering the first for the
    second leaves a suite out of a gate that then says green.
    """
    repo = _tree(tmp_path)
    assert not _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "the fixture does not start with report as a stranger to readings"
    )

    _rewrite(repo, "report/headline.py", _headline_importing("readings"))

    assert _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "an import added since the last question was not seen, so the gate "
        "would miss the suite that can now break"
    )


def test_an_edit_that_keeps_a_files_length_is_still_an_edit(tmp_path: Path) -> None:
    """Byte count cannot be the whole key, because a real break preserves it.

    The selector's own fixture file says why: its breaks replace one digit with
    another so the source keeps its length. Here the report's import moves from
    one leaf to another whose package name is the same length, so the two trees
    are the same size and only their content tells them apart. A key of
    modification time and size cannot tell them apart when the run is quick
    enough for both writes to land in one tick.
    """
    repo = _tree(tmp_path)
    _rewrite(repo, "report/headline.py", _headline_importing("readings"))
    assert _selects(repo, "readings/value.py", "report/tests/test_headline.py")

    moved = _headline_importing("readouts")
    assert len(moved) == len(_headline_importing("readings")), (
        "this test needs two versions of one file with the same byte count"
    )
    _rewrite(repo, "report/headline.py", moved)

    assert not _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "a same-length edit was not noticed, so the gate is selecting against "
        "a tree that no longer exists"
    )
    assert _selects(repo, "readouts/value.py", "report/tests/test_headline.py"), (
        "the edge the edit added was not picked up either"
    )


def test_a_file_that_disappears_is_a_different_tree(tmp_path: Path) -> None:
    """A deletion changes no other file's timestamp, so it must key on its own.

    Without that, the stamp reads as "every file I knew about is untouched" and
    a removed module keeps its importers alive in an answer the gate narrows
    against.
    """
    repo = _tree(tmp_path)
    first = _graph.build(repo)
    assert "report/headline.py" in first.first_party

    (repo / "report/headline.py").unlink()
    (repo / "report/tests/test_headline.py").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    second = _graph.build(repo)
    assert "report/headline.py" not in second.first_party, (
        "a deleted file is still in the graph, so the answer came from memory"
    )
