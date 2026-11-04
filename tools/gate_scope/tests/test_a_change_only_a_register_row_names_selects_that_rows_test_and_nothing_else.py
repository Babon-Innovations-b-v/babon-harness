"""A change only a register row names selects that row's test, and nothing else.

WHAT IT PINS. How the modules under `tools/` fit: `test_register` holds the
rows, and `gate_scope.decide` turns a commit's changed paths into the tests the
gate runs. A file no import reaches (a table a test opens, a prose page) is
found only through a row's `runs_when`, so this seam is the one place that
change is caught. The register's rows are replaced by rows written here, over a
small git repository written here, so the answer depends on nothing in the
real tree.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The repository
holds two packages whose tests import nothing that the changed file is, so no
import closure can select them. Which test should run is read off the rows by
eye: the row for `alpha` names `notes/alpha/*.md`, the row for `beta` names
`notes/beta/*.md`, and a path neither names selects nothing. A package whose
every test is chosen is handed to pytest as its directory, so the expected
selection is `alpha` or `beta`.

ONE FUNCTION. This group's one test. A new check is a parametrized case of it,
never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops the
selector adding the tests whose rows a change matched, so the two matched cases
come back with nothing selected.

GUARDS. One test per module group (#1210), 2026-11-04.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.gate_scope import decide, select
from tools.gate_scope.select import GATE_STEP
from tools.test_register import Break, Row

ALPHA_TEST = "alpha/tests/test_alpha_is_one.py"
BETA_TEST = "beta/tests/test_beta_is_two.py"

FILES = {
    "alpha/__init__.py": "",
    "alpha/value.py": "ONE = 1\n",
    ALPHA_TEST: "from alpha.value import ONE\n\n\ndef test_alpha_is_one():\n    assert ONE == 1\n",
    "beta/__init__.py": "",
    "beta/value.py": "TWO = 2\n",
    BETA_TEST: "from beta.value import TWO\n\n\ndef test_beta_is_two():\n    assert TWO == 2\n",
    "notes/alpha/page.md": "# alpha\n",
    "notes/beta/page.md": "# beta\n",
    "notes/other/page.md": "# other\n",
    GATE_STEP: "pytest -q --ignore=.claude/worktrees\n",
}

ROWS = (
    Row(test=ALPHA_TEST, pins=("alpha",), runs_when=("notes/alpha/*.md",),
        proved_by=Break(file="alpha/value.py", old="ONE = 1", new="ONE = 0", why="the value moves")),
    Row(test=BETA_TEST, pins=("beta",), runs_when=("notes/beta/*.md",),
        proved_by=Break(file="beta/value.py", old="TWO = 2", new="TWO = 0", why="the value moves")),
)

CASES = [
    pytest.param("notes/alpha/page.md", "selected", ("alpha",), id="alpha-row-selects-alpha-only"),
    pytest.param("notes/beta/page.md", "selected", ("beta",), id="beta-row-selects-beta-only"),
    pytest.param("notes/other/page.md", "none", (), id="a-path-no-row-names-selects-nothing"),
]


@pytest.mark.parametrize("changed, scope, tests", CASES)
def test_a_change_only_a_register_row_names_selects_that_rows_test_and_nothing_else(
        changed: str, scope: str, tests: tuple[str, ...], tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The decision for one changed page is the scope and the tests read off the rows by hand."""
    for relative, text in FILES.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    monkeypatch.setattr(select, "ROWS", ROWS)

    decision = decide([changed], tmp_path)

    assert (decision.scope, decision.paths) == (scope, tests), decision.reason
