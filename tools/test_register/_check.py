"""Is the register honest about the tree it describes?

OWNS: the four ways a register and a tree can disagree, and the sentence each
one is reported as. Three more are asked of their own modules and reported in
the same list: a module or module group with no test (`_coverage.py`), a second
test for one (`_second.py`), and a file holding more than one test function
(`_functions.py`).

DOES NOT OWN: replaying a break (`_replay.py`), or deciding what to do about a
problem (`.claude/hooks/pre-commit` refuses the commit, `infra/auto-deploy/steps/40-gate.sh`
refuses the deploy).

VALIDATION IS DATA. This returns a tuple of sentences, never an exception and
never a bare boolean, so the caller can print all four problems at once instead
of the committer fixing them one round trip at a time.

THE FOUR PROBLEMS.

  A test file in the tree with no row. With a row required, a new test is a
  line in one file, in the diff, where a person reads it.

  A row naming a test that is not there. The register would quietly keep
  selecting a file pytest cannot collect.

  A row whose break anchor is missing or ambiguous. A break that cannot be
  applied proves nothing, and it fails at the worst moment, which is on the
  deploy VM.

  A row with no break at all. Allowed while the test is being written, refused
  once it is committed.
"""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from ._coverage import untested
from ._functions import extra_tests
from ._groups import module_groups
from ._modules import modules_in
from ._row import Row
from ._second import second_tests

#: The filename shape pytest collects here.
_PYTHON_TEST = "test_*.py"

#: Directories with no test of ours in them: vendored code, build output, and
#: the caches every tool leaves behind. Only the fallback below uses this list;
#: where there is a git directory, git is asked instead.
_SKIP = (
    ".git/",
    ".claude/worktrees/",
    "node_modules/",
    ".venv/",
    "__pycache__/",
    "dist/",
    "build/",
)


def check(
    repo: Path,
    rows: Sequence[Row],
    *,
    require_break: bool = True,
    require_tests: bool = True,
    debt: Sequence[tuple[str, str]] = (),
    function_debt: Sequence[tuple[str, int]] = (),
    untested_debt: Sequence[str] = (),
) -> tuple[str, ...]:
    """Every disagreement between the register and the tree, as sentences.

    `debt` and `function_debt` are the known lists over the one-test-a-level
    and one-function-a-file rules (`_debt.py` for the real register); each entry
    is excused, and one whose test has no row any more is a problem.
    `require_tests` refuses a module or module group no row tests unless
    `untested_debt` names it; a scratch register in a test that is not about
    that rule turns it off.
    """
    problems: list[str] = []
    by_test = {row.test: row for row in rows}

    for test in _test_files(repo):
        if test not in by_test:
            problems.append(
                f"{test} is a test file with no row in the register. Add one with "
                f"`python3 -m tools.test_register --new <module>`, or "
                f"write the row by hand: it needs the module it pins, the paths "
                f"that select it, and the break that proves it can fail."
            )

    for row in rows:
        if not (repo / row.test).is_file():
            problems.append(f"{row.test} has a row but is not in the tree")
            continue
        problems.extend(_break_problems(repo, row, require_break=require_break))

    modules = modules_in(repo)
    if require_tests:
        problems.extend(untested(rows, set(modules), set(module_groups(modules)), untested_debt))
    problems.extend(second_tests(rows, set(modules), set(module_groups(modules)), debt))
    problems.extend(extra_tests(repo, rows, function_debt))
    return tuple(problems)


def _break_problems(repo: Path, row: Row, *, require_break: bool) -> list[str]:
    """What is wrong with one row's break, if anything."""
    if row.proved_by is None:
        if require_break:
            return [
                f"{row.test} has no break recorded, so nothing proves it can fail. "
                f"Break the module it pins, watch it go red, and write that edit down."
            ]
        return []
    target = repo / row.proved_by.file
    if not target.is_file():
        return [f"{row.test}: its break edits {row.proved_by.file}, which is not in the tree"]
    hits = target.read_text(encoding="utf-8", errors="replace").count(row.proved_by.old)
    if hits != 1:
        return [
            f"{row.test}: its break anchor appears {hits} times in "
            f"{row.proved_by.file} and must appear exactly once"
        ]
    if row.proved_by.file == row.test:
        return [f"{row.test}: its break edits the test itself, which proves nothing"]
    return []


def _test_files(repo: Path) -> tuple[str, ...]:
    """Every test file the repository OWNS, repo-relative and sorted.

    Git is asked first, and what it lists is the index, so a newly staged test
    counts and an unstaged scratch file does not. That is exactly the question
    at commit time, and it is the only reliable way to tell our tests from the
    build output beside them.

    Why a walk is not enough: build tools write copies of tests into output
    directories, and those copies are tests by every filename rule and belong
    to nobody. A skip list would have to grow a line for each tool anybody
    ever runs; the index already knows.

    The walk stays for the one tree with no index: the deploy gate runs pytest
    inside a `git archive` export, where every file present is tracked by
    construction, so the two answers agree there.
    """
    listed = _tracked(repo)
    if listed is not None:
        return listed
    found: set[str] = set()
    for path in repo.glob(f"**/{_PYTHON_TEST}"):
        relative = path.relative_to(repo).as_posix()
        if any(f"/{relative}".find(f"/{skip}") >= 0 for skip in _SKIP):
            continue
        found.add(relative)
    return tuple(sorted(found))


def _tracked(repo: Path) -> tuple[str, ...] | None:
    """The test files git lists, or `None` where git cannot be asked."""
    if not (repo / ".git").exists():
        return None
    try:
        listed = subprocess.run(
            ["git", "-c", "core.quotePath=false", "ls-files", "-z"],
            cwd=repo, capture_output=True, text=True, check=True, timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return tuple(sorted(name for name in listed.split("\0") if name and _is_a_test(name)))


def _is_a_test(name: str) -> bool:
    """True for a path whose filename is one pytest collects."""
    base = name.rsplit("/", 1)[-1]
    return base.startswith("test_") and base.endswith(".py")
