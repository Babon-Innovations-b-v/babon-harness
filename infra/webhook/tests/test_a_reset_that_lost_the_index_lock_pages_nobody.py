"""A self-heal reset that lost git's index lock to the deploy cycle pages nobody.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

WHAT IT PINS. The reset-and-decide block in `infra/webhook/trigger-deploy.sh`.
The deploy cycle's step 15 fast-forwards the same clone under its own lock,
which the listener deliberately does not take (GitHub wants an answer in
seconds). A reset that fails on the index lock lost a race to a process that is
doing the repair itself, so it is not a failure; any other failed reset is, and
must still be raised.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The shipped
block is extracted and run with a stub git printing a known message and exit
code; the expected verdict follows from the rule above.

WHAT IT WAS PROVED AGAINST. Treating every failed reset as a lost race.

GUARDS. Alerts only for what could not be fixed.
"""
from __future__ import annotations

import inspect
import pytest


# From a reset that lost the index lock pages nobody.

import re


import subprocess


from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "trigger-deploy.sh"


_BLOCK_RE = re.compile(r"^\s*reset_output=\$\(mktemp\).*?rm -f \"\$reset_output\"", re.MULTILINE | re.DOTALL)


_LOCK_MESSAGE = (
    "fatal: Unable to create '/srv/repo/.git/index.lock': File exists.\n\n"
    "Another git process seems to be running in this repository."
)


_OTHER_MESSAGE = "fatal: Could not reset index file to revision 'origin/main'."


def _run(tmp_path: Path, git_output: str, git_rc: int) -> tuple[str, str]:
    match = _BLOCK_RE.search(_SCRIPT.read_text(encoding="utf-8"))
    assert match, f"no reset-and-decide block found in {_SCRIPT}"
    stub = tmp_path / "git"
    stub.write_text(f"#!/bin/bash\ncat <<'GITEOF'\n{git_output}\nGITEOF\nexit {git_rc}\n", encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "webhook.log"
    log.touch()
    script = "\n".join((
        "set -u",
        f'export PATH="{tmp_path}:$PATH"',
        f'LOG="{log}"',
        'log() { echo "$*" >> "$LOG"; }',
        'REPO="/tmp/does-not-matter"',
        'reset_failed=""',
        match.group(0),
        'printf "RESET_FAILED=[%s]" "$reset_failed"',
    ))
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=True)
    return log.read_text(encoding="utf-8"), done.stdout


def _a_reset_that_lost_the_index_lock_pages_nobody(tmp_path: Path) -> None:
    log, result = _run(tmp_path, _LOCK_MESSAGE, git_rc=128)
    assert "RESET_FAILED=[]" in result
    assert "paging nobody" in log


def _any_other_reset_failure_is_still_a_failure(tmp_path: Path) -> None:
    log, result = _run(tmp_path, _OTHER_MESSAGE, git_rc=128)
    assert "RESET_FAILED=[1]" in result
    assert "paging nobody" not in log


def _a_reset_that_worked_is_not_a_failure(tmp_path: Path) -> None:
    log, result = _run(tmp_path, "HEAD is now at 1234567 a commit", git_rc=0)
    assert "RESET_FAILED=[]" in result
    assert "paging nobody" not in log


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
    *_cases(_a_reset_that_lost_the_index_lock_pages_nobody),
    *_cases(_any_other_reset_failure_is_still_a_failure),
    *_cases(_a_reset_that_worked_is_not_a_failure),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_reset_that_lost_the_index_lock_pages_nobody(scenario, given, uses, request):
    """A self-heal reset that lost git's index lock to the deploy cycle pages nobody: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
