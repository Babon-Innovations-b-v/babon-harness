"""A narrowed gate must still run the test that catches the break.

WHAT IT PINS. `tools.gate_scope.decide`, the seam the deploy gate calls on every
cycle (`infra/auto-deploy/steps/20-changes.sh` asks, `steps/40-gate.sh`
obeys). It is the one place where a wrong answer is silent and expensive:
`decide` says which tests one commit can reach, and everything it leaves out is
not run.

THE FAILURE IT CATCHES. A selector that drops a test which would have caught
the commit. That is invisible: the gate reports green having verified nothing
relevant, and the regression ships.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The oracle is
pytest itself. The test builds a small git repository whose import chain is
written out by hand (`report/render.py` imports `core/rules.py`,
`clock/ticks.py` imports nothing), BREAKS one file for real and runs the whole
small suite to see which tests actually go red. Every test the break kills must
be inside the selection, and the selection alone must go red.

The second test is the same shape from the other side: break the file nothing
imports, and the tests the selector dropped must be exactly the ones that still
pass. Without that half a selector that always answered "everything" would
pass.

The third needs no oracle: it is the failure policy as a property. On anything
the selector cannot reason about, the answer must be `full`. Never `none`,
never `selected`, never an exception.

The fourth checks this repository's own `.claude/` against the shared
`.claude/scripts/gate-scope.py`: a path that script calls a document must never
force the full gate here, and a path it calls code must never be inert here.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.gate_scope import decide

# The location of the gate step is read out of the selector rather than
# written here as a string. It is scaffolding, `decide` refuses to narrow
# unless it can read that step's `--ignore` flags, so the fixture repository
# has to contain one, and pinning the filename here would only mean a rename
# shows up as a confusing red in this file instead of where it belongs.
from tools.gate_scope.select import GATE_STEP

#: The fixture repository, written out by hand. The import chain is the point:
#: `report.render` reaches `core.rules`, and `clock.ticks` reaches nothing. So
#: a change to `core/rules.py` can break two of the three suites and a change
#: to `clock/ticks.py` can break exactly one, and both facts are readable here
#: without running anything.
REPO_FILES: dict[str, str] = {
    "core/__init__.py": "",
    "core/rules.py": (
        '"""The one number the whole fixture is built on."""\n'
        "\n"
        "MAX_SESSIONS_PER_DAY = 7\n"
    ),
    "core/tests/test_the_limit_is_seven.py": (
        "from core.rules import MAX_SESSIONS_PER_DAY\n"
        "\n"
        "\n"
        "def test_the_limit_is_seven():\n"
        "    assert MAX_SESSIONS_PER_DAY == 7\n"
    ),
    "report/__init__.py": "",
    "report/render.py": (
        "from core.rules import MAX_SESSIONS_PER_DAY\n"
        "\n"
        "\n"
        "def headline():\n"
        '    return "at most %d a day" % MAX_SESSIONS_PER_DAY\n'
    ),
    "report/tests/test_the_headline_names_the_limit.py": (
        "from report.render import headline\n"
        "\n"
        "\n"
        "def test_the_headline_names_the_limit():\n"
        '    assert headline() == "at most 7 a day"\n'
    ),
    "clock/__init__.py": "",
    "clock/ticks.py": "def ticks_per_second():\n    return 50\n",
    "clock/tests/test_there_are_fifty_ticks.py": (
        "from clock.ticks import ticks_per_second\n"
        "\n"
        "\n"
        "def test_there_are_fifty_ticks():\n"
        "    assert ticks_per_second() == 50\n"
    ),
    # `decide` reads the gate step's `--ignore` flags so it can never name a
    # path pytest refuses to collect. No flags at all means it cannot tell,
    # and it answers `full`; this is the input that lets it answer at all.
    GATE_STEP: "#!/usr/bin/env bash\npytest -q --ignore=vendored\n",
}

#: Every test file in the fixture, which is what pytest's default patterns
#: collect there. Written out rather than globbed, so a mistake in the fixture
#: shows up as a mismatch instead of quietly shrinking what is compared.
FIXTURE_TESTS = (
    "clock/tests/test_there_are_fifty_ticks.py",
    "core/tests/test_the_limit_is_seven.py",
    "report/tests/test_the_headline_names_the_limit.py",
)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A real git repository holding the tree above.

    Real, because `decide` asks `git ls-files` what is in the tree; that is the
    authority in a checkout and there is nothing to gain from pretending
    otherwise.
    """
    for relative, source in REPO_FILES.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run_pytest(repo: Path, targets: tuple[str, ...]) -> int:
    """Run pytest inside the fixture repository and return its exit code.

    `-m pytest` puts the repository root on `sys.path`, which is how the gate
    itself runs it (cwd and PYTHONPATH both the tree under test), so the
    fixture's `import core.rules` resolves the way a real one does.

    `PYTHONDONTWRITEBYTECODE` is not tidiness, it is the difference between
    this file testing something and testing nothing. The breaks below replace a
    digit, so the source keeps its byte count, and a `.pyc` written by the
    green run a fraction of a second earlier is still considered valid: source
    mtime is recorded in whole seconds and the size is unchanged, so without
    it every broken run would come back green off stale bytecode.
    """
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return done.returncode


def _tests_that_go_red(repo: Path) -> frozenset[str]:
    """Which of the fixture's suites actually fail, asked one file at a time.

    This is the oracle, and it is pytest rather than anything in `gate_scope`.
    One file per run, so the answer is an exit code and not a parsed report.
    """
    return frozenset(
        test for test in FIXTURE_TESTS if _run_pytest(repo, (test,)) != 0
    )


def _covered(selection: tuple[str, ...], test: str) -> bool:
    """True when the gate, handed `selection`, would collect `test`.

    A selected path is either the test file itself or a directory above it;
    pytest collects `test_*.py` under a directory argument.
    """
    return any(test == path or test.startswith(path + "/") for path in selection)


@pytest.mark.parametrize(
    ("changed", "before", "after", "expected_red"),
    [
        pytest.param(
            "core/rules.py",
            "MAX_SESSIONS_PER_DAY = 7",
            "MAX_SESSIONS_PER_DAY = 9",
            frozenset({
                "core/tests/test_the_limit_is_seven.py",
                "report/tests/test_the_headline_names_the_limit.py",
            }),
            id="a-file-two-suites-depend-on",
        ),
        pytest.param(
            "clock/ticks.py",
            "return 50",
            "return 60",
            frozenset({"clock/tests/test_there_are_fifty_ticks.py"}),
            id="a-file-nothing-else-imports",
        ),
    ],
)
def test_the_selection_holds_every_test_the_change_actually_breaks(
    fixture_repo: Path,
    changed: str,
    before: str,
    after: str,
    expected_red: frozenset[str],
) -> None:
    """Break one file for real; the narrowed gate must still go red.

    The four assertions are four different things and all of them are needed.
    That the fixture starts green, so a later red is the break and not the
    scaffolding. That the selector NARROWED (`selected`, not `full`), which is
    the feature. That every suite the break actually kills is inside the
    selection, the safety property, with the set of killed suites coming from
    running pytest rather than from the selector. And that the selection ALONE
    fails, which is the user-visible fact: the selection is what step 40 runs,
    and a green there ships the commit.
    """
    assert _run_pytest(fixture_repo, ()) == 0, (
        "the fixture repository does not start green"
    )

    decision = decide([changed], fixture_repo)
    assert decision.scope == "selected", (
        f"changing {changed} was not narrowed at all: {decision.scope} "
        f"({decision.reason})"
    )

    source = fixture_repo / changed
    original = source.read_text(encoding="utf-8")
    replaced = original.replace(before, after)
    assert replaced != original, "the break did not apply"
    source.write_text(replaced, encoding="utf-8")

    went_red = _tests_that_go_red(fixture_repo)
    assert went_red == expected_red, (
        "the fixture does not break the way this file says it does: "
        f"{sorted(went_red)}"
    )

    missed = {test for test in went_red if not _covered(decision.paths, test)}
    assert not missed, (
        f"changing {changed} breaks {sorted(missed)}, and the gate would not "
        f"have run it: the selection was {decision.paths}"
    )

    assert _run_pytest(fixture_repo, decision.paths) != 0, (
        f"the selection {decision.paths} passes on a tree that is broken"
    )


def test_a_change_nothing_imports_leaves_the_rest_of_the_suite_out(
    fixture_repo: Path,
) -> None:
    """Narrowing has to actually narrow, and what it drops has to be safe.

    The test above would be satisfied by a selector that always answered "run
    everything", which is the answer this package exists to stop giving: 62% of
    most commits cannot break most tests. So here the dropped suites are named, and then run
    against the broken tree to show that dropping them cost nothing.
    """
    decision = decide(["clock/ticks.py"], fixture_repo)
    assert decision.scope == "selected"

    dropped = [
        test for test in FIXTURE_TESTS if not _covered(decision.paths, test)
    ]
    assert dropped, (
        "every suite in the repository was selected for a change to a leaf "
        f"module, so nothing was narrowed: {decision.paths}"
    )

    ticks = fixture_repo / "clock/ticks.py"
    ticks.write_text(
        ticks.read_text(encoding="utf-8").replace("return 50", "return 60"),
        encoding="utf-8",
    )
    for test in dropped:
        assert _run_pytest(fixture_repo, (test,)) == 0, (
            f"{test} was left out of the selection and it fails on this "
            "change, which is the one mistake this selector may not make"
        )


def test_anything_it_cannot_reason_about_comes_back_as_the_whole_suite(
    fixture_repo: Path,
) -> None:
    """The failure policy, as a property: unknown means full, and never raises.

    Every case below is a commit about which nothing can honestly be said. A
    selector that answered `none` or `selected` for one of them would hand step
    40 a scope that verifies the wrong thing, and step 40 has no way to know.
    `full` costs a slow cycle; the other direction ships a regression through a
    gate that said green.
    """
    unparseable = fixture_repo / "core/typo.py"
    unparseable.write_text("def (\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fixture_repo, check=True)

    cases = {
        "no changed paths at all": ([], fixture_repo),
        "a dependency pin, which moves every import in the tree": (
            ["uv.lock"],
            fixture_repo,
        ),
        "the project file": (["pyproject.toml"], fixture_repo),
        "an extension it does not recognise": (["core/mystery.bin"], fixture_repo),
        "a .py under a hyphenated directory, which answers to no module name": (
            ["auto-deploy/gone.py"],
            fixture_repo,
        ),
        "a first-party file that does not parse": (["core/rules.py"], fixture_repo),
        "a repository it cannot read": (
            ["core/rules.py"],
            fixture_repo / "does-not-exist",
        ),
    }
    for description, (changed, repo) in cases.items():
        decision = decide(changed, repo)
        assert decision.scope == "full", (
            f"{description} was narrowed to {decision.scope}: {decision.reason}"
        )
        assert decision.paths == (), (
            f"{description} returned a full scope carrying paths, which step 40 "
            "would run instead of the suite"
        )


def test_no_test_sits_on_the_always_run_floor_without_a_register_row() -> None:
    """A floor test with no row makes `scope none` unreachable for the whole repo.

    `_floor.derive` puts a suite that READS the tree on the always-run floor,
    because a reverse-import closure cannot see a file opened at run time. A
    floor member with no row in the test register is therefore selected by every
    commit in the repository, and the cheapest tier stops existing.

    The message says how to add the row, because otherwise this failure
    surfaces somewhere else entirely, as a gate that never narrows.
    """
    from tools.gate_scope import _floor, _graph
    from tools.test_register import ROWS

    repo = Path(__file__).resolve().parents[3]
    # `_graph.build` asks `git ls-files` what the repository tracks, and that
    # module's docstring says it raises on a tree without git on purpose, so a
    # bug cannot be mistaken for an empty graph; the seam meant to catch it and
    # widen to a full gate is `select.decide`, not this test. The deploy gate
    # runs pytest inside an export with a `.git` of its own; a bare copy with
    # none is an environment, not a repository fault.
    if not (repo / ".git").exists():
        pytest.skip("no .git here, so nothing can say what the tree tracks")
    graph = _graph.build(repo)
    floor = _floor.derive(graph, repo)
    registered = {row.test for row in ROWS}

    rowless = sorted(path for path in floor if path not in registered)
    if not rowless:
        return

    raise AssertionError(
        f"{len(rowless)} test file(s) are on the deploy gate's always-run floor "
        f"with no row in the test register:\n\n  "
        + "\n  ".join(rowless)
        + "\n\nWhile that is true, `scope none` is unreachable for EVERY commit "
        "in this repository and the gate runs these tests on all of them.\n\n"
        "A test is added to the register with its file, so it cannot arrive "
        "without one:\n\n"
        "  python3 -m tools.test_register --new <module> "
        '--says "<invariant>"\n\n'
        "Then TIGHTEN `runs_when` to what the test actually opens: too wide and "
        "it is back on the floor with extra steps, too narrow and a change that "
        "breaks it will not run it."
    )



# ── `.claude/` follows the shared default's document rules ──────────────────

#: Paths under `.claude/` of every kind the harness has, written out by hand.
_CLAUDE_PATHS = (
    ".claude/soul.md",
    ".claude/skills/grill/SKILL.md",
    ".claude/skills/archify/bin/archify.mjs",
    ".claude/hooks/pre-commit",
    ".claude/hooks/commit_guard.py",
    ".claude/hooks/tests/test_issue_guard.py",
    ".claude/scripts/setup-github.py",
    ".claude/index/pin.env",
    ".claude/settings.json",
    ".claude/project.json",
)


def test_a_claude_path_is_a_document_here_exactly_when_the_shared_default_says_so() -> None:
    """Two classifiers of one directory, compared rather than trusted.

    `.claude/scripts/gate-scope.py` is the shared pre-push default every
    project gets; this selector is the grown version. Where the default says a
    path is a document, nothing in this selector may force the full suite for
    it, and where the default says code, this one may not call it inert.
    """
    import runpy

    from tools.gate_scope._classify import FULL_FORCING, INERT, classify

    repo = Path(__file__).resolve().parents[3]
    script = repo / ".claude/scripts/gate-scope.py"
    if not script.is_file():
        pytest.skip("the shared gate-scope.py is not in this tree")
    is_document = runpy.run_path(str(script))["is_document"]
    for path in _CLAUDE_PATHS:
        kind = classify(path)
        if is_document(path):
            assert kind == INERT, f"{path} is a document by the shared rules but {kind} here"
        else:
            assert kind != INERT, f"{path} is code by the shared rules but inert here"
            assert kind in (FULL_FORCING, "python"), kind
