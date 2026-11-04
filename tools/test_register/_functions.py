"""A test file holds one test, and a file over that is refused with its count.

OWNS: counting the tests in one test file, and the one-test-a-file rule as
`--check` enforces it: a test file is ONE `test_*` function (pytest) or ONE
`test(`/`it(` block (node). Parametrized cases are one function, so the same
check on different inputs is still one test, and that is how cases are added:
parametrized, never pasted in as a second function.

DOES NOT OWN: the one-test-per-level rule (`_second.py`), the known debt
(`_debt.py`, handed in by `__main__.py`).

WHY. The level rule alone let a module keep its one test file and stack check
after check into it: one file of 41 functions is one row and passes. The rule
exists to keep tests efficient and meaningful, so a module's checks are MERGED
into one test of the answer that matters, never concatenated.

WHO IS EXCUSED. A file on `FUNCTION_DEBT` up to the count it had the day the
rule arrived, and nothing else; a note excuses nothing (`_second.py` says why).
The debt only shrinks: a debt file that grows is refused, one that shrank must
lower its entry to its new count, and one down to a single test, or gone, must
lose its entry.

VALIDATION IS DATA, like `_check.py`: sentences, never an exception.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from pathlib import Path

from ._row import Row

#: A node test: a `test(` or `it(` call opening a line, `.only`/`.skip` included.
_NODE_TEST = re.compile(r"^\s*(?:test|it)(?:\.(?:only|skip|todo))?\s*\(", re.MULTILINE)


def tests_in(path: Path) -> int:
    """How many tests one file holds, or -1 when a python file does not parse."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".py":
        return len(_NODE_TEST.findall(text))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return -1
    return sum(_tests_at(node) for node in tree.body)


def _tests_at(node: ast.stmt) -> int:
    """The pytest tests one top-level statement defines: a function, or a `Test*` class's methods."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return int(node.name.startswith("test"))
    if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
        return sum(
            1
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name.startswith("test")
        )
    return 0


def extra_tests(
    repo: Path, rows: Sequence[Row], debt_list: Sequence[tuple[str, int]] = ()
) -> tuple[str, ...]:
    """Every file holding more tests than one, or than its debt entry, and every stale entry."""
    debt = dict(debt_list)
    problems = []
    for row in rows:
        path = repo / row.test
        if not path.is_file():
            continue
        count = tests_in(path)
        owed = debt.get(row.test)
        if owed is not None:
            problems.extend(_against_debt(row.test, count, owed))
        elif count > 1:
            problems.append(_refusal(row.test, count))
    present = {row.test for row in rows}
    problems.extend(
        f"{test} is on FUNCTION_DEBT in _debt.py but has no row any more: delete its entry"
        for test in debt
        if test not in present
    )
    return tuple(problems)


def _against_debt(test: str, count: int, owed: int) -> list[str]:
    if count > owed:
        return [
            f"{test} holds {count} tests and its debt entry allows {owed}: a debt "
            f"file may not grow. Merge the new check into one of its tests."
        ]
    if count <= 1:
        return [f"{test} holds {count} test now: delete its FUNCTION_DEBT entry in _debt.py"]
    if count < owed:
        return [f"{test} holds {count} tests now: lower its FUNCTION_DEBT entry from {owed} to {count}"]
    return []


def _refusal(test: str, count: int) -> str:
    return (
        f"{test} holds {count} tests, and the rule is one test a file. Merge "
        f"its checks into one test of the answer that matters (parametrize the "
        f"same check over inputs); a note does not excuse a second test."
    )
