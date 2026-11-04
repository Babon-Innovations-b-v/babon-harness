"""The gate runs every test a change can break, on a graph rebuilt when the tree moves, in the environment the nightly audit checks.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A narrowed gate must still run the test that catches the break.

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

A remembered answer is only reused for the tree it was built from.

WHAT IT PINS. The memory in `_graph.build` and `_floor.derive`. Both are pure
functions of the tree and both are expensive, so an answer is remembered,
keyed on a hash of every first-party source's content.

WHY THIS TEST AND NOT THE SPEED. Speed is the reason the memory exists and it is
not the risk. The risk is a gate selecting against a tree that has since changed,
which is the one direction this package may not fail in: a scope narrower than
the change deserves is a green gate on code nobody ran. So this file asks the
only question that matters about a remembered answer, which is whether it is let
go of.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three trees are
built here whose right answers follow from the import edges this file writes,
never from what the selector said a moment earlier. An edge is added, so a suite
that could not break now can. The edge is then repointed at a package whose name
is the same length, so the two versions of the file are the same size; a key of
`(mtime_ns, size)` would see no change when two writes land inside one
filesystem tick. And a file is deleted, which
touches no other file at all.

WHAT IT WAS PROVED AGAINST. The break drops the stamp from the graph's key, so a
tree's path alone decides, and every second answer is the first one again.

GUARDS. The selector's memory.

The control that licenses narrowing has to be about the thing it licenses.

WHAT IT PINS. The four ways `audit_full_run.sh` and `steps/40-gate.sh` have to
agree, because the audit's whole job is to answer whether the gate's narrowing
dropped a test that would have failed. It can only answer that if the two run
the same suite the same way: the same ignore list, the same clean environment,
the same tree, and an interpreter belonging to that tree.

WHY IT EXISTS. The audit licenses the gate to narrow. An audit that ran a
different suite, in a different tree or a different environment, is not
evidence about the gate in either direction: a green licenses narrowing it did
not check, and a red pins every cycle to the full suite until a person clears
the marker by hand. Running it in the clone instead of an export, or through the
clone's interpreter, are the two easy ways to get that wrong.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Not from either
script's own words. The `env -i` list is read out of BOTH shipped files and
compared to each other, so neither is the authority and a change to one without
the other is what fails. The ignore list is the same construction: `40-gate.sh`
is the only source, and the audit greps it rather than restating it, which the
audit's own header calls out. The interpreter is asked a structural question with
one right answer: the run's tree and its interpreter must come from the same
place, and the clone is not that place.

WHAT IS DELIBERATELY NOT PINNED. The gate may run pytest-xdist workers
(GATE_PYTEST_WORKERS) and the audit runs one process. A test that only fails
under xdist passes the audit; the audit's question is which tests the SELECTION
dropped, which running them all answers.

WHAT IT WAS PROVED AGAINST. The break points the audit's pytest back at the
clone's venv.

GUARDS. The narrowing licence.
"""
from __future__ import annotations

import inspect


# From the gate runs every test the change can break.

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


def _the_selection_holds_every_test_the_change_actually_breaks(
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


def _a_change_nothing_imports_leaves_the_rest_of_the_suite_out(
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


def _anything_it_cannot_reason_about_comes_back_as_the_whole_suite(
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


def _no_test_sits_on_the_always_run_floor_without_a_register_row() -> None:
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


def _a_claude_path_is_a_document_here_exactly_when_the_shared_default_says_so() -> None:
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

# From the graph is rebuilt when the tree moves under it.

from tools.gate_scope import _graph


from tools.gate_scope.select import GATE_STEP as GATE_STEP_2, decide as decide_2


#: The two leaves. Separate top-level packages, because the selector answers at
#: directory granularity and two modules in one package cannot be told apart in
#: its answer. Their names are the SAME LENGTH, which is what makes the
#: byte-count case below possible.
_LEAF = "def value() -> int:\n    return 50\n"


_LEAF_TEST = (
    "from {package}.value import value\n\n\n"
    "def test_value() -> None:\n    assert value() == 50\n"
)


#: A tree where `report` imports neither leaf, so changing a leaf can only
#: break that leaf's own suite.
_TREE = {
    "readings/__init__.py": "",
    "readings/value.py": _LEAF,
    "readings/tests/__init__.py": "",
    "readings/tests/test_value.py": _LEAF_TEST.format(package="readings"),
    "readouts/__init__.py": "",
    "readouts/value.py": _LEAF,
    "readouts/tests/__init__.py": "",
    "readouts/tests/test_value.py": _LEAF_TEST.format(package="readouts"),
    "report/__init__.py": "",
    "report/headline.py": "def headline() -> str:\n    return 'steady'\n",
    "report/tests/__init__.py": "",
    "report/tests/test_headline.py": (
        "from report.headline import headline\n\n\n"
        "def test_headline() -> None:\n    assert headline() == 'steady'\n"
    ),
    # The selector reads the gate's own ignore list and answers `full` without
    # it, which would make every assertion here pass for the wrong reason.
    GATE_STEP_2: "#!/usr/bin/env bash\npytest -q --ignore=vendored\n",
}


def _headline_importing(package: str) -> str:
    """`report/headline.py` written to import one named leaf.

    `readings` and `readouts` are the same length, so the two versions of this
    file are the same size and a stamp counting only bytes would call them one
    tree.
    """
    return (
        f"from {package}.value import value\n\n\n"
        "def headline() -> str:\n    return 'steady' if value() else 'flat'\n"
    )


def _tree(root: Path) -> Path:
    """Write the tree and put it under git, which is what the selector asks."""
    for relative, source in _TREE.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _rewrite(repo: Path, relative: str, source: str) -> None:
    """Change one file and tell git, the way an ordinary edit would."""
    (repo / relative).write_text(source, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)


def _selects(repo: Path, changed: str, test: str) -> bool:
    """Would the gate run `test` for a change to `changed`?

    `decide` answers with the directories it would hand pytest, so containment
    is what "selected" means.
    """
    decision = decide_2([changed], repo)
    return any(
        test == path or test.startswith(path.rstrip("/") + "/")
        for path in decision.paths
    )


def _an_import_added_since_the_last_question_is_seen(tmp_path: Path) -> None:
    """The tree grows an edge between two questions, so the answer must grow.

    Before, `readings` is a stranger to the report and only its own suite can
    break. After, the report imports it. A selector answering the first for the
    second leaves a suite out of a gate that then says green.
    """
    repo = _tree(tmp_path)
    assert not _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "the fixture does not start with report as a stranger to readings"
    )

    _rewrite(repo, "report/headline.py", _headline_importing("readings"))

    assert _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "an import added since the last question was not seen, so the gate "
        "would miss the suite that can now break"
    )


def _an_edit_that_keeps_a_files_length_is_still_an_edit(tmp_path: Path) -> None:
    """Byte count cannot be the whole key, because a real break preserves it.

    The selector's own fixture file says why: its breaks replace one digit with
    another so the source keeps its length. Here the report's import moves from
    one leaf to another whose package name is the same length, so the two trees
    are the same size and only their content tells them apart. A key of
    modification time and size cannot tell them apart when the run is quick
    enough for both writes to land in one tick.
    """
    repo = _tree(tmp_path)
    _rewrite(repo, "report/headline.py", _headline_importing("readings"))
    assert _selects(repo, "readings/value.py", "report/tests/test_headline.py")

    moved = _headline_importing("readouts")
    assert len(moved) == len(_headline_importing("readings")), (
        "this test needs two versions of one file with the same byte count"
    )
    _rewrite(repo, "report/headline.py", moved)

    assert not _selects(repo, "readings/value.py", "report/tests/test_headline.py"), (
        "a same-length edit was not noticed, so the gate is selecting against "
        "a tree that no longer exists"
    )
    assert _selects(repo, "readouts/value.py", "report/tests/test_headline.py"), (
        "the edge the edit added was not picked up either"
    )


def _a_file_that_disappears_is_a_different_tree(tmp_path: Path) -> None:
    """A deletion changes no other file's timestamp, so it must key on its own.

    Without that, the stamp reads as "every file I knew about is untouched" and
    a removed module keeps its importers alive in an answer the gate narrows
    against.
    """
    repo = _tree(tmp_path)
    first = _graph.build(repo)
    assert "report/headline.py" in first.first_party

    (repo / "report/headline.py").unlink()
    (repo / "report/tests/test_headline.py").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    second = _graph.build(repo)
    assert "report/headline.py" not in second.first_party, (
        "a deleted file is still in the graph, so the answer came from memory"
    )

# From the nightly audit runs the suite the gate would run in the environment the gate would run it in.

import re


#: `<repo>/tools/gate_scope/tests/` is three below the root.
_REPO = Path(__file__).resolve().parents[3]


_AUDIT = _REPO / "tools/gate_scope/audit_full_run.sh"


_GATE = _REPO / "infra/auto-deploy/steps/40-gate.sh"


#: A variable set on an `env -i` line, e.g. `PYTHONPATH="$BUILD_TREE"`.
_ENV_ASSIGNMENT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _clean_environment(script: Path) -> set[str]:
    """The variables a script hands to its `env -i` pytest run.

    Read from the `env -i` line to the `timeout` that ends it, which is the
    shape both scripts write and the only place either of them uses `env -i`.
    """
    text = script.read_text(encoding="utf-8")
    blocks = []
    for start in (match.end() for match in re.finditer(r"env -i", text)):
        stop = text.find("timeout", start)
        assert stop > start, f"an `env -i` in {script.name} never reaches its run"
        blocks.append(text[start:stop])
    assert blocks, f"{script.name} does not run pytest under `env -i`"
    return {
        name
        for block in blocks
        for name in _ENV_ASSIGNMENT.findall(block)
    }


#: What the gate sets and the audit does not. Empty: anything appearing on
#: either side alone is drift, which is what this makes visible.
_GATE_ONLY: frozenset[str] = frozenset()


def _both_runs_get_the_same_clean_environment() -> None:
    """One list, written twice, so it is compared rather than trusted.

    Both scripts say in their own comments to keep the list identical, and a
    comment cannot enforce that. Either file may be the one that moved: the
    assertion names neither as the authority.
    """
    audit = _clean_environment(_AUDIT)
    gate = _clean_environment(_GATE)

    assert not audit - gate, (
        "the nightly audit hands pytest settings the gate does not, so a test "
        f"can pass one and fail the other: {sorted(audit - gate)}"
    )
    assert gate - audit == _GATE_ONLY, (
        "the gate and the audit have drifted apart on the environment they run "
        "in, and the audit is only evidence about the gate while they agree: "
        f"gate only {sorted(gate - audit)}, expected {sorted(_GATE_ONLY)}"
    )


def _the_audit_takes_its_ignore_list_from_the_gate_and_never_restates_it() -> None:
    """A second copy of the list is a second suite nobody compared.

    The list moves with the repository. Any spelling of it here that is not a
    read of the gate's own file is a copy that will drift.
    """
    audit = _AUDIT.read_text(encoding="utf-8")
    assert "40-gate.sh" in audit, (
        "the audit no longer reads the gate's file for the ignore list"
    )
    #: The flags themselves may only appear as the pattern being grepped for,
    #: never as literal values this script carries.
    literal_flags = [
        line
        for line in audit.splitlines()
        if "--ignore=" in line
        and "grep" not in line
        and not line.lstrip().startswith("#")
    ]
    assert not literal_flags, (
        f"the audit spells out ignore flags of its own: {literal_flags}"
    )


def _the_audit_runs_the_export_with_the_exports_own_interpreter() -> None:
    """Tree and interpreter move together or the run reads two trees.

    An editable install in the clone's venv resolves to an absolute path inside
    the clone, and `PYTHONPATH` cannot shadow it. So an interpreter taken from
    the clone imports that package from the clone and everything else from the
    export, which is the reading the export exists to stop.
    """
    audit = _AUDIT.read_text(encoding="utf-8")
    run_lines = [line for line in audit.splitlines() if "/bin/pytest" in line]
    assert run_lines, "the audit does not run a pytest at all"

    from_the_clone = [line for line in run_lines if "$REPO/.venv" in line]
    assert not from_the_clone, (
        "the audit runs the export's tests through the clone's interpreter, so "
        f"its answer is about neither tree: {from_the_clone}"
    )

    assert any("audit_venv" in line for line in run_lines), (
        "the audit's pytest does not come from an environment built for the "
        f"tree under audit: {run_lines}"
    )
    assert "UV_PROJECT_ENVIRONMENT" in audit, (
        "nothing in the audit builds that environment"
    )


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
    *_cases(_the_selection_holds_every_test_the_change_actually_breaks, 
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
),
    *_cases(_a_change_nothing_imports_leaves_the_rest_of_the_suite_out),
    *_cases(_anything_it_cannot_reason_about_comes_back_as_the_whole_suite),
    *_cases(_no_test_sits_on_the_always_run_floor_without_a_register_row),
    *_cases(_a_claude_path_is_a_document_here_exactly_when_the_shared_default_says_so),
    *_cases(_an_import_added_since_the_last_question_is_seen),
    *_cases(_an_edit_that_keeps_a_files_length_is_still_an_edit),
    *_cases(_a_file_that_disappears_is_a_different_tree),
    *_cases(_both_runs_get_the_same_clean_environment),
    *_cases(_the_audit_takes_its_ignore_list_from_the_gate_and_never_restates_it),
    *_cases(_the_audit_runs_the_export_with_the_exports_own_interpreter),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_gate_runs_every_test_a_change_can_break_on_a_fresh_graph_in_the_environment_the_audit_checks(scenario, given, uses, request):
    """The gate runs every test a change can break, on a graph rebuilt when the tree moves, in the environment the nightly audit checks: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
