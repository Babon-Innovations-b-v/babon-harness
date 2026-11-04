"""A red is the commit's, a test's or the box's, sorted as the rule written out by hand says.

WHAT IT PINS. `tools.red_triage`, at its public seam: `triage`, and the same
rule from the shell (`python3 -m tools.red_triage`, JSON in, lines out).

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every case is a
synthetic ground truth: three made-up runs over test files named `a`, `b` and
`c`, and the answer read off the rule in the module docstring by hand. A file
that passes on the re-run flipped; a file that fails on the re-run and on the
last good tree is old, unless the commit added or changed it; anything else
that failed twice is the commit's; a run that could not run (None) decides
nothing.

WHAT IT WAS PROVED AGAINST. The row's break drops `- new_files` from the old
set, so a test the commit changed reads as old and is quarantined, and the
"a changed test is never old" case fails. Dropping the `good_failing is None`
arm turns the "last good tree could not run" case from setup into a quarantine.

GUARDS. Nothing ever holds the deploy queue.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.red_triage import COMMIT, FLIPPED, OLD, SETUP, TEST, Triage, triage

_REPO = Path(__file__).resolve().parents[3]

_CASES = {
    "a red naming no file is the commit's": (
        (), (), (), (), Triage(COMMIT)),
    "a re-run that could not run decides nothing": (
        ("a",), None, ("a",), (), Triage(SETUP)),
    "a last good tree that could not run decides nothing for a file that failed twice": (
        ("a",), ("a",), None, (), Triage(SETUP)),
    "a file that passes on the re-run flipped and leaves the gate": (
        ("a",), (), None, (), Triage(TEST, (("a", FLIPPED),))),
    "a file that fails on the last good tree too is old and leaves the gate": (
        ("a",), ("a",), ("a",), (), Triage(TEST, (("a", OLD),))),
    "a file that fails twice and passes on the last good tree is the commit's": (
        ("a",), ("a",), (), (), Triage(COMMIT)),
    "a changed test is never old": (
        ("a",), ("a",), ("a",), ("a",), Triage(COMMIT)),
    "a changed test that flips still leaves the gate": (
        ("a",), (), (), ("a",), Triage(TEST, (("a", FLIPPED),))),
    "one commit's file makes the red the commit's, and the tests beside it still leave": (
        ("a", "b", "c"), ("a", "b"), ("b",), (), Triage(COMMIT, (("c", FLIPPED), ("b", OLD)))),
}


def _shell(failing, rerun, good, new) -> str:
    """The same answers through the command line, as the gate step sends them."""
    answers = {"failing": list(failing), "rerun_failing": None if rerun is None else list(rerun),
               "good_failing": None if good is None else list(good), "new_files": list(new)}
    return subprocess.run([sys.executable, "-m", "tools.red_triage"], input=json.dumps(answers), text=True,
                          capture_output=True, check=True, cwd=_REPO).stdout


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_red_is_the_commits_the_tests_or_the_boxs(case: str) -> None:
    failing, rerun, good, new, expected = _CASES[case]
    answer = triage(frozenset(failing), None if rerun is None else frozenset(rerun),
                    None if good is None else frozenset(good), frozenset(new))
    assert answer == expected
    lines = [expected.kind, *(f"quarantine\t{test}\t{reason}" for test, reason in expected.quarantine)]
    assert _shell(failing, rerun, good, new).splitlines() == lines
