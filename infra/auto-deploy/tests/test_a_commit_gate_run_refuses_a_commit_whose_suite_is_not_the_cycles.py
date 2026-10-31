"""A verifying run's verdict is only about the suite the deploy cycle runs.

WHAT IT PINS. The refusal at the top of `commit_gate/run_one.sh`: the run reads
the gate's `--ignore` list out of the commit under test AND out of the clone the
cycle sources its steps from, and refuses (exit 79) unless the two are equal.

WHY. The cycle runs the suite its clone's 40-gate.sh names, while a verifying
run tests an older commit that may name another. The verdict cache key (sha,
scope, tree) cannot see the difference, so a verdict about a different suite
would be replayed as the cycle's own.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Real git
repositories are built whose two step files agree, disagree, or name no list,
and the shipped refusal is extracted and run against each. The expected exit
code follows from the rule above.

WHAT IT WAS PROVED AGAINST. Comparing only the commit's list with itself, so a
mismatch with the clone falls through.

GUARDS. The verdict cache.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_LANE = Path(__file__).resolve().parents[1] / "commit_gate" / "run_one.sh"

#: The line the refusal opens on: the path of the step file it compares.
_GUARD_OPENS = 'GATE_STEP_PATH="infra/auto-deploy/steps/40-gate.sh"'

#: The last line of the refusal. Both arms exit 79; this closes the second.
_GUARD_CLOSES = "fi"

#: What a `40-gate.sh` has to contain for the comparison to have an answer.
#: Only the `--ignore=` flags are read, so the rest of the file is not modelled.
_IGNORES_A = "pytest --ignore=.claude/worktrees --ignore=vendor\n"
_IGNORES_B = "pytest --ignore=.claude/worktrees\n"


def _guard() -> str:
    """The refusal: the `GATE_STEP_PATH` line to the `fi` that closes it.

    Found by its own two `exit 79` arms rather than by counting keywords, for
    the same reason the step-40 chain test gives: a regex for the first `fi`
    stops inside the first arm and silently tests half the thing.
    """
    lines = _LANE.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line == _GUARD_OPENS]
    assert len(starts) == 1, f"expected one ignore-list refusal in {_LANE}, found {len(starts)}"

    arms = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "exit 79" and index > starts[0]
    ]
    assert len(arms) == 2, f"the refusal in {_LANE} has {len(arms)} arms, expected 2"

    for index in range(arms[-1], len(lines)):
        if lines[index] == _GUARD_CLOSES:
            return "\n".join(lines[starts[0]: index + 1])
    raise AssertionError(f"the ignore-list refusal in {_LANE} never closes")


def _git(repo: Path, *args: str) -> str:
    """One git command in one repository, failing loudly."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return done.stdout.strip()


def _repo_with_two_gate_files(tmp_path: Path, committed: str, on_disk: str) -> tuple[Path, str]:
    """A clone whose HEAD `40-gate.sh` differs from the commit under test's.

    Returns the clone and the sha of the commit under test. `committed` is what
    that commit's step file says; `on_disk` is what the clone's working tree
    says, which is what the cycle would run.
    """
    repo = tmp_path / "clone"
    step = repo / "infra" / "auto-deploy" / "steps"
    step.mkdir(parents=True)
    (step / "40-gate.sh").write_text(committed, encoding="utf-8")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the commit the lane is testing")
    sha = _git(repo, "rev-parse", "HEAD")

    if on_disk != committed:
        (step / "40-gate.sh").write_text(on_disk, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "the commit the clone has moved to")
    return repo, sha


def _run_guard(tmp_path: Path, repo: Path, sha: str) -> int:
    """Run the shipped refusal against one repository. Returns its exit code.

    `0` means it fell through, which is the lane going on to produce a verdict.
    """
    script = "\n".join((
        "set -u",
        'log() { :; }',
        f'REPO="{repo}"',
        f'SHA="{sha}"',
        _guard(),
        "exit 0",
    ))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    return done.returncode


def test_a_run_whose_suite_is_the_cycles_suite_goes_on(tmp_path: Path) -> None:
    """Both lists the same is the ordinary case, and it must not be refused.

    Without this the other cases pass for a refusal that refuses everything,
    which would stop the lane producing any verdict at all.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, _IGNORES_A, _IGNORES_A)
    assert _run_guard(tmp_path, repo, sha) == 0


def test_a_run_whose_ignore_list_came_from_another_commit_is_refused(
    tmp_path: Path,
) -> None:
    """The commit says one suite and the clone says another, so neither is safe.

    This is the whole failure: the verdict would be about a suite the cycle does
    not run, and nothing downstream could tell, because the cache key does not
    carry the list.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, _IGNORES_A, _IGNORES_B)
    assert _run_guard(tmp_path, repo, sha) == 79


@pytest.mark.parametrize(
    ("committed", "on_disk"),
    [
        pytest.param("pytest -q\n", _IGNORES_A, id="the commit names no ignore list"),
        pytest.param(_IGNORES_A, "pytest -q\n", id="the clone names no ignore list"),
    ],
)
def test_a_run_that_cannot_read_both_lists_is_refused(
    tmp_path: Path, committed: str, on_disk: str
) -> None:
    """Unreadable is not the same as equal, and it may not be treated as equal.

    An empty list on either side means the comparison has no answer, so the run
    cannot know which suite it is. It refuses rather than guessing.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, committed, on_disk)
    assert _run_guard(tmp_path, repo, sha) == 79


def test_the_only_clone_file_the_lane_opens_is_the_one_it_compares() -> None:
    """A second clone read is a second way for the two commits to differ.

    The refusal above closes exactly one hole: the ignore list. Every other file
    the lane needs comes out of `$WORK`, the export of the commit under test, so
    a new `$REPO/`-rooted file read is a new mismatch nothing checks. Reads that
    name a sha (`git -C "$REPO" show|archive|ls-tree <sha>`) are object reads and
    are not this: they are immutable, and a working tree is not.
    """
    lines = _LANE.read_text(encoding="utf-8").splitlines()
    opened = [
        line.strip()
        for line in lines
        if '"$REPO/' in line and not line.lstrip().startswith("#")
    ]
    assert opened == ['CLONE_IGNORES="$(_cg_ignore_flags < "$REPO/$GATE_STEP_PATH" 2>/dev/null)"'], (
        "run_one.sh reads a file out of the clone that the ignore-list refusal "
        f"does not compare: {opened}"
    )
