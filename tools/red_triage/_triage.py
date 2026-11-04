"""Whose fault a red gate is: the commit's, a test's, or the box's.

OWNS: the rule that sorts one red run, given what three runs of its failing
test files said.

DOES NOT OWN: running anything (the gate step runs the two extra runs and acts
on the answer), the quarantine itself (`tools/test_register`, a row's
`quarantined` field and the issue for its owner), or the eject.

THE RULE: nothing ever holds the queue. A red is either a WRONG COMMIT or a
WRONG TEST. A failing test file is the test's fault when

  it flips    the same commit, run again on a fresh runner, passes it; or
  it is old   it also fails on the last good tree, the one the deploy shipped.

Every other failing file is the commit's: it failed twice on this tree and
passes on the last good one, or it is new or changed in this commit, where the
last good tree runs other code and cannot speak for it, so a test the commit
changed can never be old (only a flip can take it out). One commit's file makes
the whole red the commit's, and the commit is reverted on main and handed back
at once, as the eject does; any test's file found beside it is still
quarantined, because it would red the next commit too. A red that is only the
tests' quarantines them and the deploy goes on with the rest, with no time
limit on the quarantine.

A RUN THAT COULD NOT HAPPEN DECIDES NOTHING. When the re-run or the last good
tree's run could not start or finish, there is no evidence either way and the
answer is `setup`: the box, run again, never a revert and never a quarantine. A
red that names no test file is the commit's here; the gate runs its whole
selection once more before it asks, so one that flips never gets this far.

FAILURE POLICY. Pure: no I/O, no exception for any input.
"""
from __future__ import annotations

from dataclasses import dataclass

COMMIT = "commit"
TEST = "test"
SETUP = "setup"

FLIPPED = "passes when the same commit runs it again"
OLD = "fails on the last good tree too"


@dataclass(frozen=True)
class Triage:
    """The answer: whose fault, and which test files leave the gate and why."""

    kind: str
    quarantine: tuple[tuple[str, str], ...] = ()


def triage(
    failing: frozenset[str],
    rerun_failing: frozenset[str] | None,
    good_failing: frozenset[str] | None,
    new_files: frozenset[str] = frozenset(),
) -> Triage:
    """Sort one red run.

    `failing` is the test files the red run named; `rerun_failing` those the
    same commit failed again (None: the re-run could not run); `good_failing`
    those the last good tree failed (None: that run could not run);
    `new_files` those the last good tree does not have or this commit changed.
    """
    if not failing:
        return Triage(COMMIT)
    if rerun_failing is None:
        return Triage(SETUP)
    flipped = sorted(failing - rerun_failing)
    still = failing & rerun_failing
    if still and good_failing is None:
        return Triage(SETUP)
    old = sorted(still & (good_failing or frozenset()) - new_files)
    commits = still - set(old)
    quarantine = tuple((test, FLIPPED) for test in flipped) + tuple((test, OLD) for test in old)
    return Triage(COMMIT if commits else TEST, quarantine)
