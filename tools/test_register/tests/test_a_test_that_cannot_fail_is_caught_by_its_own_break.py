"""The register's verdict on a scratch repository is the one written out by hand.

WHAT IT PINS. The register's public acts, at the seam the command line calls.
`replay` applies a row's break, runs that row's test and says whether the test
noticed, which is the whole point of the register. `check` says what the
register refuses in a tree: a test file with no row, a break that edits the
test itself, a second test for one module or one module group, and a test file
holding more than one test function. Each rule has its debt list and no other
exception, and every debt list only shrinks. `scaffold`, what `--new` calls,
writes a new test file and its row.

ONE TEST, PARAMETRIZED. Every case is the same question, "what does the
register answer here", asked of a different scratch repository. That is the
rule this file enforces on every other test, so it keeps it itself.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every case is a
synthetic ground truth: a scratch tree built inside the test and the answer
written out by hand from the rule.

The replay cases write one module, `calc.py`, whose `add` the break turns into
subtraction, and one test whose verdict is known by reading it:

  a real test    asserts `add(2, 2) == 4`, so it MUST go red.
  a blind test   asserts only that `add` returns an int; the break keeps it
                 green, so `replay` must say `green`, which is the finding.
  a skipping     skips; pytest exits 0 having verified nothing, and calling
                 that proof is the mistake this file exists to stop.

After every replay `calc.py` must hold its original bytes, and a planted
`__pycache__/calc.*.pyc` must be gone whenever a break was applied, because
bytecode compiled while the break was applied makes later tests fail against a
tree version control calls clean.

The register cases build a tree with two modules, `pkg/alpha` and `pkg/beta`,
so `pkg` is the module group above them by the written rule; a layer with code
(`pkg/alpha/gates`, `pkg/shared`) and test data (`pkg/beta/fixtures`) fold into
the level that owns them. Each case's level and function count are read off the
case by hand, and each expected refusal is matched by the start of its
sentence, which names the file or level.

The scaffold cases write the expected files out from the rule. A tests
directory the call creates gets its `__init__.py`; one that already existed
keeps its own shape. The filename is every word of the sentence, lowercased,
apostrophes (straight and typographic) dropped from inside the word.

WHAT IT WAS PROVED AGAINST. The row's break makes `_read` call a passing run
`red`, so the blind case fails. Dropping `len(fresh) > 1` from `_second.py`
lets two fresh tests of `pkg/alpha` pass and the "a second test of a module"
case fails; dropping the `count > 1` refusal in `_functions.py` turns the
"three tests" case red; writing the package marker whenever it is absent, or
dropping the apostrophe `.replace(...)`, in `_scaffold.py` turns a scaffold
case red.

GUARDS. The register's reason to exist: a test that cannot fail looks exactly
like a good one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.test_register import Break, Row, check, replay, scaffold
from tools.test_register._replay import GREEN, RED, UNPROVEN

#: The module under the replay cases. `add` is written the obvious way so the
#: break below is the obvious fault.
_MODULE = "def add(left, right):\n    return left + right\n"

#: The break: addition becomes subtraction. A test that checks the ANSWER dies
#: on it; a test that checks only the shape does not.
_BREAK = Break(file="calc.py", old="return left + right", new="return left - right", why="add subtracts")
_MOVED = Break(file="calc.py", old="return left * right", new="return 0", why="gone")

_REAL_TEST = "from calc import add\n\n\ndef test_two_and_two() -> None:\n    assert add(2, 2) == 4\n"
_BLIND_TEST = (
    "from calc import add\n\n\ndef test_it_returns_a_number() -> None:\n"
    "    assert isinstance(add(2, 2), int)\n"
)
_SKIPPING_TEST = (
    "import pytest\n\npytestmark = pytest.mark.skip(reason='nothing to check here')\n\n\n"
    "def test_nothing() -> None:\n    assert False\n"
)

#: The case the break is aimed at skips (no runner on this box), a second case
#: passes regardless, and the file exits 0 with something passed. Only the
#: DEFAULT runner sees pytest's summary line, so these cases use it.
_HALF_SKIPPING_TEST = (
    "import pytest\n\nfrom calc import add\n\n\n"
    "@pytest.mark.skip(reason='needs a runner this box does not have')\n"
    "def test_two_and_two() -> None:\n    assert add(2, 2) == 4\n\n\n"
    "def test_something_else_entirely() -> None:\n    assert True\n"
)

_ONE, _TWO, _THREE = "pkg/alpha/tests/test_one.py", "pkg/alpha/tests/test_two.py", "pkg/tests/test_three.py"
_TESTS = (_ONE, _TWO, _THREE)
_PY_ONE = "def test_it() -> None:\n    assert True\n"
_PY_THREE = _PY_ONE + "\n\ndef test_b() -> None:\n    assert True\n\n\nclass TestC:\n    def test_c(self) -> None:\n        assert True\n"

#: Two more modules under `pkg/alpha`, which makes it a group as well as a module.
_ALPHA_IS_A_GROUP = {
    f"pkg/alpha/{module}/{name}": text
    for module in ("one", "two")
    for name, text in (("__init__.py", ""), ("code.py", "VALUE = 3\n"))
}

#: The register a scaffold case's scratch repository starts with.
_ROWS = "tools/test_register/_rows.py"
_EMPTY_REGISTER = "from ._row import Break, Row\n\nROWS = (\n)\n"

#: How the replay case runs its test: a subprocess with the scratch directory
#: importable, or the register's own runner.
_THERE, _DEFAULT = "there", "default"


def _row(test: str, *pins: str, note: str = "") -> Row:
    return Row(test=test, pins=pins, runs_when=(f"{pins[0]}/**",), note=note)


def _replays(body: str, proved_by: Break, runner: str, verdict: str, phrase: str) -> tuple:
    """A replay case: the scratch test, its break, how it runs, and the answer."""
    return ("replay", body, proved_by, runner, verdict, phrase)


def _checks(rows: tuple, contents: dict, debt=(), function_debt=(), refusals=(), pkg=True) -> tuple:
    """A register case: the rows, the files, the two debt lists, the refusals."""
    return ("check", rows, contents, debt, function_debt, refusals, pkg)


def _scaffolds(module: str, sentence: str, files: tuple, before=None) -> tuple:
    """A scaffold case: what is called on, and the files the module's tests directory holds after."""
    return ("scaffold", module, sentence, files, before or {})


_CASES = {
    "replay: a test that checks the answer goes red on its break": _replays(
        _REAL_TEST, _BREAK, _THERE, RED, "went red on its break"),
    "replay: a test that checks only the shape passed with its break": _replays(
        _BLIND_TEST, _BREAK, _THERE, GREEN, "PASSED with its own break applied"),
    "replay: a run in which everything skipped proves nothing": _replays(
        _SKIPPING_TEST, _BREAK, _DEFAULT, UNPROVEN, "skipped everything"),
    "replay: a run where the case the break targets skipped proves nothing": _replays(
        _HALF_SKIPPING_TEST, _BREAK, _DEFAULT, UNPROVEN, "part of it skipped"),
    "replay: a break whose anchor is not there proves nothing": _replays(
        _REAL_TEST, _MOVED, _THERE, UNPROVEN, "exactly once"),
    "check: a test file with no row": _checks(
        (), {"test_nobody_registered_me.py": _REAL_TEST}, pkg=False,
        refusals=("test_nobody_registered_me.py is a test file with no row",)),
    "check: build output beside our tests is not ours to register": _checks(
        (), {"web/node_modules/some-package/test_shipped_with_the_package.py": _PY_ONE}, pkg=False),
    "check: a break that edits the test itself": _checks(
        (Row(test="test_real.py", pins=("",), runs_when=("calc.py",),
             proved_by=Break(file="test_real.py", old="add(2, 2) == 4", new="add(2, 2) == 5", why="no")),),
        {"test_real.py": _REAL_TEST}, pkg=False,
        refusals=("test_real.py: its break edits the test itself, which proves nothing",)),
    "check: one test per module and per group is clean": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/beta"), _row(_THREE, "pkg")), {}),
    "check: a second test of a module": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/alpha/a.py")), {},
        refusals=("pkg/alpha would have 2 tests",)),
    "check: a second test of a group": _checks(
        (_row(_ONE, "pkg"), _row(_TWO, "pkg/alpha", "pkg/beta")), {}, refusals=("pkg would have 2 tests",)),
    "check: a written reason does not excuse a second test": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/alpha", note="second test: a live database")), {},
        refusals=("pkg/alpha would have 2 tests",)),
    "check: debt excuses what is on it and no third": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/alpha"), _row(_THREE, "pkg/alpha")), {},
        debt=(("pkg/alpha", _ONE), ("pkg/alpha", _TWO)), refusals=("pkg/alpha would have 3 tests",)),
    "check: a debt entry whose test is gone": _checks(
        (_row(_ONE, "pkg/alpha"),), {}, debt=(("pkg/alpha", "pkg/alpha/tests/test_gone.py"),),
        refusals=("pkg/alpha/tests/test_gone.py is on the debt list",)),
    "check: a pin in a layer of a module counts for the module": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/alpha/gates")), {},
        refusals=("pkg/alpha would have 2 tests",)),
    "check: a pin in a layer of a group counts for the group": _checks(
        (_row(_ONE, "pkg"), _row(_TWO, "pkg/shared")), {}, refusals=("pkg would have 2 tests",)),
    "check: a pin in test data counts for its module": _checks(
        (_row(_ONE, "pkg/beta"), _row(_TWO, "pkg/beta/fixtures")), {},
        refusals=("pkg/beta would have 2 tests",)),
    "check: a module that is a group too": _checks(
        (_row(_ONE, "pkg/alpha"), _row(_TWO, "pkg/alpha/one", "pkg/alpha/two"),
         _row(_THREE, "pkg/alpha/one", "pkg/alpha/two")), _ALPHA_IS_A_GROUP,
        refusals=("pkg/alpha (group) would have 2 tests",)),
    "check: a file of three test functions, a class's method among them": _checks(
        (_row(_ONE, "pkg/alpha"),), {_ONE: _PY_THREE}, refusals=(f"{_ONE} holds 3 tests",)),
    "check: a written reason does not excuse a second function": _checks(
        (_row(_ONE, "pkg/alpha", note="second test: two ports"),), {_ONE: _PY_THREE},
        refusals=(f"{_ONE} holds 3 tests",)),
    "check: a function debt file at its count": _checks(
        (_row(_ONE, "pkg/alpha"),), {_ONE: _PY_THREE}, function_debt=((_ONE, 3),)),
    "check: a function debt file that grew": _checks(
        (_row(_ONE, "pkg/alpha"),), {_ONE: _PY_THREE}, function_debt=((_ONE, 2),),
        refusals=(f"{_ONE} holds 3 tests and",)),
    "check: a function debt file that shrank": _checks(
        (_row(_ONE, "pkg/alpha"),), {_ONE: _PY_THREE}, function_debt=((_ONE, 5),),
        refusals=(f"{_ONE} holds 3 tests now",)),
    "check: a function debt file down to one": _checks(
        (_row(_ONE, "pkg/alpha"),), {}, function_debt=((_ONE, 4),), refusals=(f"{_ONE} holds 1 test now",)),
    "check: a function debt entry whose test is gone": _checks(
        (_row(_ONE, "pkg/alpha"),), {}, function_debt=(("pkg/tests/test_gone.py", 2),),
        refusals=("pkg/tests/test_gone.py is on FUNCTION_DEBT",)),
    "scaffold: a tests directory it creates gets its package marker": _scaffolds(
        "gadgets", "a gadget turns", ("gadgets/tests/__init__.py", "gadgets/tests/test_a_gadget_turns.py")),
    "scaffold: a tests directory with no marker keeps its own shape": _scaffolds(
        "widgets", "a widget turns",
        ("widgets/tests/test_a_widget_turns.py", "widgets/tests/test_something_already_here.py"),
        before={"widgets/tests/test_something_already_here.py": _PY_ONE}),
    "scaffold: a straight apostrophe keeps its word in the filename": _scaffolds(
        "widgets", "the widget's own label",
        ("widgets/tests/__init__.py", "widgets/tests/test_the_widgets_own_label.py")),
    "scaffold: a typographic apostrophe keeps its word in the filename": _scaffolds(
        "widgets", "a door’s hinge turns",
        ("widgets/tests/__init__.py", "widgets/tests/test_a_doors_hinge_turns.py")),
}


def _write(root: Path, contents: dict[str, str]) -> None:
    for relative, text in contents.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")


def _tree(root: Path, contents: dict[str, str]) -> None:
    """Two modules under one group, what folds into them, and the test files the rows name."""
    for module, source in (("pkg/alpha", "a.py"), ("pkg/beta", "b.py")):
        _write(root, {f"{module}/__init__.py": "", f"{module}/{source}": "VALUE = 1\n"})
    _write(root, {"pkg/__init__.py": ""})
    for folded in ("pkg/alpha/gates", "pkg/shared", "pkg/beta/fixtures"):
        _write(root, {f"{folded}/__init__.py": "", f"{folded}/code.py": "VALUE = 2\n"})
    for test in _TESTS:
        _write(root, {test: contents.get(test, _PY_ONE)})
    _write(root, {relative: text for relative, text in contents.items() if relative not in _TESTS})


def _run_there(row: Row, repo: Path) -> int:
    """Run the scratch test with the scratch directory importable."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly", row.test],
        cwd=repo, capture_output=True, text=True, check=False, env={"PATH": "/usr/bin:/bin"},
    ).returncode


def _replay_answer(root: Path, case: tuple) -> None:
    """Replay one scratch row; the module comes back byte for byte and no broken bytecode stays."""
    _kind, body, proved_by, runner, verdict, phrase = case
    _write(root, {"calc.py": _MODULE, "test_scratch.py": body,
                  "__pycache__/calc.cpython-312.pyc": "pretend this was compiled while the break was applied"})
    before = (root / "calc.py").read_bytes()
    row = Row(test="test_scratch.py", pins=("",), runs_when=("calc.py",), proved_by=proved_by)

    answer, sentence = replay(row, root, run=_run_there if runner == _THERE else None)

    assert (answer, phrase in sentence) == (verdict, True), sentence
    assert (root / "calc.py").read_bytes() == before
    applied = proved_by.old in _MODULE
    assert (root / "__pycache__/calc.cpython-312.pyc").exists() is not applied


def _register_answer(root: Path, case: tuple) -> None:
    """What `check` refuses, each refusal matched by the start of its sentence."""
    _kind, rows, contents, debt, function_debt, refusals, pkg = case
    if pkg:
        _tree(root, contents)
        named = {row.test for row in rows}
        rows = rows + tuple(_row(test, f"elsewhere/{test}") for test in _TESTS if test not in named)
    else:
        _write(root, {"calc.py": _MODULE, **contents})

    verdict = sorted(check(root, rows, require_break=False, debt=debt, function_debt=function_debt))

    assert len(verdict) == len(refusals), verdict
    for expected in refusals:
        assert any(sentence.startswith(expected) for sentence in verdict), (expected, verdict)


def _scaffold_answer(root: Path, case: tuple) -> None:
    """What `scaffold` writes into a scratch repository with an empty register."""
    _kind, module, sentence, files, before = case
    _write(root, {_ROWS: _EMPTY_REGISTER, f"{module}/__init__.py": '"""A module."""\n', **before})

    test, _rows = scaffold(module, sentence, root)

    directory = root / test.rsplit("/", 1)[0]
    assert sorted(path.relative_to(root).as_posix() for path in directory.iterdir()) == list(files)
    assert test in files


@pytest.mark.parametrize("case", sorted(_CASES))
def test_the_register_answers_each_scratch_repository_as_written(tmp_path: Path, case: str) -> None:
    kind = _CASES[case][0]
    if kind == "replay":
        _replay_answer(tmp_path, _CASES[case])
    elif kind == "scaffold":
        _scaffold_answer(tmp_path, _CASES[case])
    else:
        _register_answer(tmp_path, _CASES[case])
