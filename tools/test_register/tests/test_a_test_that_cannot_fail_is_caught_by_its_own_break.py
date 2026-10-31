"""A test that passes with its own break applied must be reported, not counted.

WHAT IT PINS. `replay`, which is the whole point of the register: it applies a
row's break, runs that row's test, and says whether the test noticed. Everything
else here is bookkeeping; this is the part that decides whether a green gate
means anything.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three tiny
modules are written into a scratch directory, each with a test whose verdict is
known by reading it, not by asking `replay`:

  a real test    asserts `add(2, 2) == 4`; the break makes `add` subtract, so
                 it MUST go red.
  a blind test   asserts only that `add` returns an int; the same break keeps
                 it green, so `replay` must say `green`, which is the finding.
  a skipping     skips unconditionally; pytest exits 0 having verified nothing,
                 and calling that proof is the mistake this file exists to stop.

Nothing here compares against a number `replay` produced earlier, and none of
the three modules imports the register.

WHAT IT WAS PROVED AGAINST. Making `_read` treat exit 0 as `red` turns the
blind case green-to-red and the file fails; so does dropping the `finally` that
restores the file, which leaves the scratch module broken and fails the
restore assertion.

GUARDS. The register's reason to exist.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.test_register import Break, Row, check, replay
from tools.test_register._replay import GREEN, RED, UNPROVEN

#: The module under the scratch tests. `add` is written the obvious way so the
#: break below is the obvious fault.
_MODULE = "def add(left, right):\n    return left + right\n"

#: The break: addition becomes subtraction. A test that checks the ANSWER dies
#: on it; a test that checks only the shape does not.
_BREAK = Break(file="calc.py", old="return left + right", new="return left - right", why="add subtracts")

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
#: passes regardless, and the file exits 0 with something passed.
_HALF_SKIPPING_TEST = (
    "import pytest\n\nfrom calc import add\n\n\n"
    "@pytest.mark.skip(reason='needs a runner this box does not have')\n"
    "def test_two_and_two() -> None:\n    assert add(2, 2) == 4\n\n\n"
    "def test_something_else_entirely() -> None:\n    assert True\n"
)


def _scratch(tmp_path: Path, test_name: str, body: str) -> tuple[Path, Row]:
    """A one-module repository whose single test is `body`."""
    (tmp_path / "calc.py").write_text(_MODULE, encoding="utf-8")
    (tmp_path / test_name).write_text(body, encoding="utf-8")
    return tmp_path, Row(test=test_name, pins=("",), runs_when=("calc.py",), proved_by=_BREAK)


def _run_there(row: Row, repo: Path) -> int:
    """Run the scratch test with the scratch directory importable."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly", row.test],
        cwd=repo, capture_output=True, text=True, check=False, env={"PATH": "/usr/bin:/bin"},
    ).returncode


def test_a_test_that_checks_the_answer_goes_red_on_its_break(tmp_path: Path) -> None:
    """The ordinary case: the break kills the test, so the row is honest."""
    repo, row = _scratch(tmp_path, "test_real.py", _REAL_TEST)
    verdict, sentence = replay(row, repo, run=_run_there)
    assert verdict == RED, sentence


def test_a_test_that_checks_only_the_shape_is_reported_as_unfalsifiable(tmp_path: Path) -> None:
    """The finding: it passed with its own break applied, so it checks nothing."""
    repo, row = _scratch(tmp_path, "test_blind.py", _BLIND_TEST)
    verdict, sentence = replay(row, repo, run=_run_there)
    assert verdict == GREEN, sentence


def test_a_run_that_skipped_everything_proves_nothing(tmp_path: Path) -> None:
    """pytest exits 0 when everything skips, and 0 must not read as proof."""
    repo, row = _scratch(tmp_path, "test_skips.py", _SKIPPING_TEST)
    verdict, sentence = replay(row, repo)
    assert verdict == UNPROVEN, sentence


def test_a_run_where_the_case_the_break_targets_skipped_proves_nothing(tmp_path: Path) -> None:
    """A skip anywhere in the file makes a passing run unproven, never green.

    A file whose targeted cases skip where a tool is absent, beside a case that
    passes regardless, would otherwise read as "the test survived its own
    break", and a commit would be reverted for a test that had never run.
    """
    repo, row = _scratch(tmp_path, "test_half_skips.py", _HALF_SKIPPING_TEST)
    # The DEFAULT runner, deliberately: the rule lives there, because only the
    # runner sees pytest's summary line. A stub that returns a bare exit code
    # cannot tell a clean pass from a pass with the important half skipped.
    verdict, sentence = replay(row, repo)
    assert verdict == UNPROVEN, sentence
    assert "skipped" in sentence


def test_the_module_is_put_back_whatever_the_verdict(tmp_path: Path) -> None:
    """A replay leaves the tree exactly as it found it, byte for byte."""
    repo, row = _scratch(tmp_path, "test_real.py", _REAL_TEST)
    before = (repo / "calc.py").read_bytes()
    replay(row, repo, run=_run_there)
    assert (repo / "calc.py").read_bytes() == before


def test_no_bytecode_from_the_broken_source_is_left_behind(tmp_path: Path) -> None:
    """Restoring the bytes is not enough: the cached broken code must go too.

    A `__pycache__` holding code compiled while the break was applied makes
    later tests fail against a tree version control calls clean, with the right
    source on disk and the wrong code running. This asserts that state cannot
    survive a replay.
    """
    repo, row = _scratch(tmp_path, "test_real.py", _REAL_TEST)
    cache = repo / "__pycache__"
    cache.mkdir()
    stale = cache / "calc.cpython-312.pyc"
    stale.write_bytes(b"pretend this was compiled while the break was applied")
    replay(row, repo, run=_run_there)
    assert not stale.exists(), "bytecode compiled while the break was applied survived"


def test_a_break_whose_anchor_is_not_there_proves_nothing(tmp_path: Path) -> None:
    """An anchor that has moved is unproven, never a silent pass."""
    repo, row = _scratch(tmp_path, "test_real.py", _REAL_TEST)
    moved = Row(
        test=row.test,
        pins=row.pins,
        runs_when=row.runs_when,
        proved_by=Break(file="calc.py", old="return left * right", new="return 0", why="gone"),
    )
    verdict, sentence = replay(moved, repo, run=_run_there)
    assert verdict == UNPROVEN, sentence
    assert "exactly once" in sentence


def test_a_test_file_with_no_row_is_a_problem_the_check_reports(tmp_path: Path) -> None:
    """An unregistered test file is caught: the tree is checked against the register."""
    (tmp_path / "calc.py").write_text(_MODULE, encoding="utf-8")
    (tmp_path / "test_nobody_registered_me.py").write_text(_REAL_TEST, encoding="utf-8")
    problems = check(tmp_path, ())
    assert len(problems) == 1, problems
    assert "test_nobody_registered_me.py" in problems[0]


def test_build_output_beside_our_tests_is_not_ours_to_register(tmp_path: Path) -> None:
    """A compiled copy of a test is a build artefact, not a test with no row.

    Build tools write copies of tests into output directories; those copies
    belong to nobody, and reporting them would make the pre-commit hook refuse
    every commit on that machine.

    The scratch repository here has no git directory, so this drives the WALK,
    the fallback the deploy gate's export uses. The tracked-file path is
    exercised by this repository itself on every run of the check.
    """
    (tmp_path / "calc.py").write_text(_MODULE, encoding="utf-8")
    build = tmp_path / "web/node_modules/some-package"
    build.mkdir(parents=True)
    (build / "test_shipped_with_the_package.py").write_text("def test_x(): pass\n", encoding="utf-8")
    assert check(tmp_path, ()) == ()


def test_a_row_whose_break_edits_the_test_itself_is_a_problem(tmp_path: Path) -> None:
    """Breaking the test to prove the test can fail proves nothing about the code."""
    (tmp_path / "test_real.py").write_text(_REAL_TEST, encoding="utf-8")
    row = Row(
        test="test_real.py",
        pins=("",),
        runs_when=("calc.py",),
        proved_by=Break(file="test_real.py", old="add(2, 2) == 4", new="add(2, 2) == 5", why="no"),
    )
    problems = check(tmp_path, (row,))
    assert any("proves nothing" in problem for problem in problems), problems
