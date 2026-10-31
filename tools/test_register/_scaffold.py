"""Write a new test and its row together, so the row cannot be forgotten.

OWNS: the module-test template, and the one act that puts a test file and its
register row in the tree at the same moment.

DOES NOT OWN: what a row means (`_row.py`), or whether the register and the
tree agree afterwards (`_check.py`).

WHY A COMMAND AND NOT A FILE TO COPY. A template on disk says what a test
should look like and says nothing about the row, so the row is still
remembered or not. A command that writes both cannot have that failure mode.

WHAT THE TEMPLATE CARRIES. The filename is the sentence the test proves, so a
reader knows what breaks from the name alone. The docstring says what the test
pins, what fault it was proved against, and which issue or decision it guards.
The body feeds a KNOWN input and checks an answer worked out without calling
the code under test, because deriving the expected value from the thing being
tested is self-consistency, not a test.
"""
from __future__ import annotations

import posixpath
from pathlib import Path

TEMPLATE = '''"""<One sentence: the invariant this pins, in plain words.>

WHAT IT PINS. <Which module, and which behaviour of it. Name the seam the test
crosses: the public interface, never an internal.>

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. <The hard part.
A hand-computed number, a published vector, a value read out of a specification,
a property that must hold whatever the constants are. If you cannot say this,
the test is self-consistency and does not belong here.>

WHAT IT WAS PROVED AGAINST. <The break in this test's register row, in one
sentence. `python3 -m tools.test_register --replay {test}` applies it
and demands red.>

GUARDS. <#issue or decision, and the date, if there is one.>
"""
from __future__ import annotations


def test_{name}() -> None:
    """<What this one case asserts.>"""
    raise AssertionError("write the test, then run --replay to prove it can fail")
'''

ROW_TEMPLATE = '''    Row(
        test="{test}",
        pins=({pins}),
        runs_when=(
{runs_when}        ),
        proved_by=Break(
            file="<the file the break edits, never this test>",
            old="<an exact substring of that file, appearing exactly once>",
            new="<what it becomes: a realistic fault, not a syntax error>",
            why="<which assertion this trips, in one sentence>",
        ),
    ),
'''


def scaffold(module: str, sentence: str, repo: Path) -> tuple[str, str]:
    """Write the test file and its register row. Returns both paths.

    `sentence` is the invariant in words, and it becomes the filename: "a saved
    widget comes back unchanged" becomes
    `test_a_saved_widget_comes_back_unchanged.py`.
    """
    name = "_".join(_filename_words(sentence))
    if not name:
        raise ValueError("the sentence must contain words that can become a filename")

    test = f"{module}/tests/test_{name}.py"
    target = repo / test
    if target.exists():
        raise FileExistsError(f"{test} is already there")

    # Only a tests directory this call CREATES gets the package marker; a
    # directory that already holds tests keeps whatever shape it has.
    #
    # And only when the name is free. pytest names a test module from its
    # basedir: walk up while `__init__.py` exists, and the first directory
    # without one goes on `sys.path`. Two `tests` packages under trees that are
    # not themselves importable (a hyphen in a parent name, say) both come out
    # as plain `tests`, and a run collecting both dies with exit code 2, which
    # the gate reads as red for everybody.
    tests_dir = target.parent
    is_new_directory = not tests_dir.exists()
    if is_new_directory:
        taken = _package_named(repo, _dotted_name(tests_dir))
        if taken is not None:
            raise FileExistsError(
                f"a tests package named `{_dotted_name(tests_dir)}` is already "
                f"at {taken}, and a second one would make the two a single "
                f"module that cannot be imported together. Put the test in "
                f"{taken} instead, or leave the new directory without an "
                f"`__init__.py` so pytest collects it by path."
            )
        tests_dir.mkdir(parents=True)
        (tests_dir / "__init__.py").write_text(
            f'"""Tests for `{module}`."""\n',
            encoding="utf-8",
        )
    target.write_text(TEMPLATE.format(name=name, test=test), encoding="utf-8")

    rows_file = repo / "tools/test_register/_rows.py"
    _append_row(rows_file, test=test, module=module)
    return test, rows_file.relative_to(repo).as_posix()


def _filename_words(sentence: str) -> list[str]:
    """The words of `sentence` that can stand in a filename, lowercased.

    An apostrophe is dropped from inside a word rather than dropping the word,
    so "the widget's own label" keeps "widgets".
    """
    plain = sentence.lower().replace("-", " ").replace("'", "").replace("\u2019", "")
    return [word for word in plain.split() if word.isalnum()]


def _dotted_name(directory: Path) -> str:
    """The module name pytest would give this package directory.

    Walk up while `__init__.py` exists; the first directory without one is the
    `sys.path` root, and the segments below it are the dotted name. Written
    here rather than borrowed, because this package is stdlib-only and runs on
    the deploy machine before any venv exists.
    """
    parts = [directory.name]
    walker = directory.parent
    while (walker / "__init__.py").exists():
        parts.append(walker.name)
        walker = walker.parent
    return ".".join(reversed(parts))


def _package_named(repo: Path, name: str) -> str | None:
    """Where a tests package of this name already sits, if one does."""
    for marker in repo.rglob("tests/__init__.py"):
        relative = marker.parent.relative_to(repo).as_posix()
        if relative.startswith((".venv/", ".claude/worktrees/")):
            continue
        if "node_modules/" in relative + "/":
            continue
        if _dotted_name(marker.parent) == name:
            return relative
    return None


def _append_row(rows_file: Path, *, test: str, module: str) -> None:
    """Build the python row: the module's own directory is its trigger."""
    trigger = f'        "{posixpath.dirname(test).removesuffix("/tests")}/**",\n'
    _insert_row(rows_file, ROW_TEMPLATE.format(test=test, pins=f'"{module}",', runs_when=trigger))


def _insert_row(rows_file: Path, row: str) -> None:
    """Put a row at the end of the register, before its closing bracket."""
    source = rows_file.read_text(encoding="utf-8")
    closing = source.rstrip().rfind(")")
    if closing < 0:
        raise ValueError(f"{rows_file} does not end in a tuple this can extend")
    rows_file.write_text(source[:closing] + row + source[closing:], encoding="utf-8")
