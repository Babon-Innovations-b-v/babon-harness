"""Adding a test leaves the shape of its tests directory alone.

WHAT IT PINS. `tools.test_register.scaffold`, at the public seam the
`--new` command calls: what it writes beside the test file.

A tests directory this repository already has is one of two shapes: with an
`__init__.py` or without one, collected by path. Both work. Which one a
directory is, is not `scaffold`'s business, and a directory it did not create
is not its to convert: turning a directory into a package changes how pytest
names every module in it, which can turn the gate red on the one command whose
whole purpose is to stop a bad test arriving unnoticed.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the rule,
not from the function: a directory that existed before the call has whatever
marker it had before the call, and a directory the call creates gets the one
the per-package convention asks for. Both cases are built by hand here, so the expected file list
is written out rather than read back from what `scaffold` did.

WHAT IT WAS PROVED AGAINST. Its register row puts back the condition this
replaced, which wrote the marker whenever it was absent.

GUARDS. The per-package tests convention.
"""
from __future__ import annotations

from pathlib import Path

from tools.test_register import scaffold

#: The smallest tree `scaffold` can write into: a module, and the register file
#: it appends the row to.
_ROWS = "tools/test_register/_rows.py"
_EMPTY_REGISTER = "from ._row import Break, Row\n\nROWS = (\n)\n"


def _repo(tmp_path: Path, module: str) -> Path:
    """A scratch repository holding one module and an empty register."""
    (tmp_path / module).mkdir(parents=True)
    (tmp_path / module / "__init__.py").write_text('"""A module."""\n', encoding="utf-8")
    rows = tmp_path / _ROWS
    rows.parent.mkdir(parents=True, exist_ok=True)
    rows.write_text(_EMPTY_REGISTER, encoding="utf-8")
    return tmp_path


def test_a_tests_directory_that_already_exists_keeps_its_own_shape(tmp_path: Path) -> None:
    """A directory with tests and no package marker does not gain one."""
    repo = _repo(tmp_path, "widgets")
    tests = repo / "widgets/tests"
    tests.mkdir()
    (tests / "test_something_already_here.py").write_text("def test_x(): pass\n", encoding="utf-8")

    scaffold("widgets", "a widget turns", repo)

    assert sorted(path.name for path in tests.iterdir()) == [
        "test_a_widget_turns.py",
        "test_something_already_here.py",
    ], "scaffold added a file beside the test; the directory had no package marker"


def test_a_tests_directory_scaffold_creates_gets_its_package_marker(tmp_path: Path) -> None:
    """A brand-new tests directory is still given its package marker."""
    repo = _repo(tmp_path, "gadgets")

    scaffold("gadgets", "a gadget turns", repo)

    tests = repo / "gadgets/tests"
    assert sorted(path.name for path in tests.iterdir()) == [
        "__init__.py",
        "test_a_gadget_turns.py",
    ], "a tests directory scaffold created is missing the marker the per-package convention asks for"
