"""The register's verdict on a scratch repository is the one written out by hand.

WHAT IT PINS. The register's public acts, at the seam the command line calls.
`replay` applies a row's break, runs that row's test and says whether the test
noticed, which is the whole point of the register. `check` says what the
register refuses in a tree: a test file with no row, a break that edits the
test itself, a second test for one module or one module group, and a test file
holding more than one test function. Each rule has its debt list and no other
exception, and every debt list only shrinks. `scaffold`, what `--new` calls,
writes a new test file and its row.

The quarantine is the one field the gate writes on a row. `with_quarantine`
writes it, `quarantined_tests` reads it back, and `gate_quarantines` believes
only a line the gate's own address added; `--check --base --author` refuses a
line any other author adds. `left_out` takes the honoured quarantines out of
one selection and says when that emptied it; `owner_login`, `quarantine_issue`
and `quarantine_note` say who is told and what, from a project file written in
the case.

A test is sealed at birth. `live_reads` names every place a test's source
reads the live machine, the wall clock or the network; each sealed case is a
small test source and its findings written out by hand, line by line, from the
rule in `birth/_scan.py`, and a docstring naming `/opt`, a clock read given its
own argument and a stub `kubectl` the test wrote into `tmp_path` are not
findings. `--check --base` refuses such a test only when this change gives it
its first row. `sealed_argv` is the `docker run` the commit hook uses, written
out flag by flag (network off, the tree at its own path, a worktree's git
directory read-only beside it, a clean `env -i`, the fake clock). `read_pin`
and `pin_drift` read the gate image pin and name the inputs that moved since
the commit it was built from, in a scratch git repository.

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

The quarantine cases commit each quarantine line in a scratch git repository
as the author the case names, and the believed and refused lists are read off
the case. The selection cases name their paths and quarantines and the answer
by hand from the rule in `_quarantine.py`.

WHAT IT WAS PROVED AGAINST. The row's break makes `_read` call a passing run
`red`, so the blind case fails. Dropping `len(fresh) > 1` from `_second.py`
lets two fresh tests of `pkg/alpha` pass and the "a second test of a module"
case fails; dropping the `count > 1` refusal in `_functions.py` turns the
"three tests" case red; writing the package marker whenever it is absent, or
dropping the apostrophe `.replace(...)`, in `_scaffold.py` turns a scaffold
case red. Dropping the author test from `gate_quarantines` turns the "another
author's line" case red, and dropping `not in out` from `left_out` the
selection cases. Dropping the clock pair `("time", "time")`, the `/opt`
prefix or `"kubectl"` from `birth/_scan.py`, or `--network none` from
`birth/_run.py`, turns a sealed case red.

GUARDS. The register's reason to exist: a test that cannot fail looks exactly
like a good one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.test_register import (
    Break,
    LeftOut,
    Row,
    check,
    gate_quarantines,
    left_out,
    owner_login,
    quarantine_issue,
    quarantine_note,
    quarantined_tests,
    replay,
    scaffold,
    with_quarantine,
)
from tools.test_register import Pin, live_reads, pin_drift, read_pin, sealed_argv
from tools.test_register import __main__ as register_main
from tools.test_register.__main__ import _quarantines_refused
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

#: The quarantine cases' two authors: the gate, and anybody else.
_GATE, _PERSON = "gate@example.org", "someone@example.org"

#: The project file the owner cases read: two people, two areas, a backlog PRD.
_PROJECT = {"owner": "owner-login", "people": {"sam": "sam-login", "kim": "kim-login"},
            "areas": ["web", "pkg"], "area_label_prefix": "area:", "backlog_prd": 7}

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


def _quarantines(commits: tuple, believed: tuple, refused: tuple) -> tuple:
    """A quarantine case: (author, test) commits in order, what the gate believes, what `--check` refuses."""
    return ("quarantine", commits, believed, refused)


def _selects(selection: tuple, quarantined: tuple, expected: LeftOut) -> tuple:
    """A selection case: the gate's selection, the honoured quarantines, and what runs."""
    return ("left-out", selection, quarantined, expected)


def _seals(source: str, findings: tuple = ()) -> tuple:
    """A sealed case: one test source and every live read in it, in line order."""
    return ("sealed", source, findings)


_SEALED_TEST = (
    '"""Reads /opt/service and time.time() only in this sentence."""\n'
    "import subprocess\n"
    "import time\n"
    "def test_it(tmp_path):\n"
    "    stub = tmp_path / 'kubectl'\n"
    "    stub.write_text('#!/bin/sh\\necho pods\\n')\n"
    "    subprocess.run([str(stub), 'get', 'pods'])\n"
    "    assert time.gmtime(0).tm_year == 1970\n"
)
_CLOCK_TEST = (
    "import datetime, time\n"
    "started = time.time()\n"
    "today = datetime.datetime.now(datetime.timezone.utc)\n"
    "day = datetime.date.today()\n"
    "stamp = time.localtime()\n"
)
_NETWORK_TEST = "import requests\nfrom urllib import request\nfrom urllib.parse import quote\nimport socket\n"
_MACHINE_TEST = (
    "import os, shutil, subprocess\n"
    "from pathlib import Path\n"
    "state = Path('/opt/service/state').read_text()\n"
    "subprocess.run(['kubectl', 'get', 'pods'])\n"
    "has_docker = shutil.which('docker')\n"
    "os.system('systemctl status caddy')\n"
    "home = Path.home()\n"
    "logs = open('/var/lib/service/log')\n"
)

#: The pytest half of the sealed run, written out from the rule.
_GATE_PYTEST = (
    "env", "-i", "HOME=/home/gate", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
    "PYTHONPATH={root}", "LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1", "FAKETIME=-10000d",
    "timeout", "300", "/opt/gate-env/bin/pytest", "-q", "--no-header", "-p", "no:randomly",
    "-p", "no:cacheprovider", "pkg/tests/test_one.py",
)


def _seal_runs(root: str, git_dir: str, mounts: tuple) -> tuple:
    """A sealed-run case: where the tree and its git directory are, and the mounts the run must carry."""
    return ("sealed-run", root, git_dir, mounts)


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
    "quarantine: the gate's own line is believed and never refused": _quarantines(
        ((_GATE, _ONE),), (_ONE,), ()),
    "quarantine: another author's line is not believed and is refused": _quarantines(
        ((_GATE, _ONE), (_PERSON, _TWO)), (_ONE,), (_TWO,)),
    "quarantine: a test the gate quarantines twice is listed once": _quarantines(
        ((_GATE, _ONE), (_GATE, _ONE), (_GATE, _THREE)), (_ONE, _THREE), ()),
    "left out: a quarantined file the selection names leaves the run": _selects(
        (_ONE, _TWO), (_ONE,), LeftOut(paths=(_TWO,), ignores=(), emptied=False)),
    "left out: a quarantined file under a selected directory is ignored": _selects(
        ("pkg/alpha", _THREE), (_ONE, "other/tests/test_x.py"),
        LeftOut(paths=("pkg/alpha", _THREE), ignores=(_ONE,), emptied=False)),
    "left out: a selection the quarantine empties says so": _selects(
        (_ONE,), (_ONE,), LeftOut(paths=(), ignores=(), emptied=True)),
    "left out: an empty selection is not emptied by the quarantine": _selects(
        (), (_ONE,), LeftOut(paths=(), ignores=(), emptied=False)),
    "owner: a row naming a person, a login, and nobody": ("owner",),
    "sealed: a test that builds its own input reads nothing live": _seals(_SEALED_TEST),
    "sealed: every wall clock read is named": _seals(_CLOCK_TEST, (
        "line 2: time.time() reads the wall clock",
        "line 3: datetime.now() reads the wall clock",
        "line 4: date.today() reads the wall clock",
        "line 5: time.localtime() reads the wall clock")),
    "sealed: every network module is named": _seals(_NETWORK_TEST, (
        "line 1: imports requests, which reads the network",
        "line 2: imports urllib.request, which reads the network",
        "line 4: imports socket, which reads the network")),
    "sealed: every read of this machine is named": _seals(_MACHINE_TEST, (
        "line 3: Path() reads /opt/service/state on this machine",
        "line 4: runs kubectl, which reads this machine",
        "line 5: looks for docker on this machine",
        "line 6: runs systemctl, which reads this machine",
        "line 7: Path.home() reads this machine",
        "line 8: open() reads /var/lib/service/log on this machine")),
    "sealed: a new test that reads the clock is refused, an old one is not": ("born",),
    "sealed-run: a checkout whose git directory is inside the tree": _seal_runs(
        "/src/repo", "/src/repo/.git", ("-v", "/src/repo:/src/repo")),
    "sealed-run: a worktree whose git directory is elsewhere is mounted read-only": _seal_runs(
        "/src/wt", "/src/repo/.git", ("-v", "/src/wt:/src/wt", "-v", "/src/repo/.git:/src/repo/.git:ro")),
    "pin: the digest, the commit it was built from, and the inputs that moved": ("pin",),
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


def _quarantine_answer(root: Path, case: tuple, monkeypatch) -> None:
    """What the gate believes, and what `--check` refuses, after each author's quarantine commit."""
    _kind, commits, believed, refused = case
    monkeypatch.setenv("GATE_AUTHOR_EMAIL", _GATE)
    rows = "".join(
        f"    Row(\n        test='{test}',\n        pins=('pkg',),\n        runs_when=('pkg/**',),\n    ),\n"
        for test in _TESTS
    )
    _write(root, {_ROWS: f"from ._row import Break, Row\n\nROWS = (\n{rows})\n"})
    _commit(root, _PERSON, "rows")
    target = root / _ROWS
    for index, (author, test) in enumerate(commits):
        before = target.read_text(encoding="utf-8")
        target.write_text(with_quarantine(before, test, f"c0ffee{index}", "flips", str(index), "2000-01-01"),
                          encoding="utf-8")
        base = root.parent / f"{root.name}-base.py"
        base.write_text(before, encoding="utf-8")
        refusals = _quarantines_refused(root, str(base), author)
        assert [sentence.split(" ", 1)[0] for sentence in refusals] == ([test] if test in refused else [])
        _commit(root, author, f"quarantine {index}")
    assert quarantined_tests(root) == tuple(sorted({test for _author, test in commits}))
    assert gate_quarantines(root, author=_GATE) == believed


def _commit(root: Path, author: str, message: str) -> None:
    """One commit of everything in the scratch repository, authored by `author`."""
    who = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": author, "GIT_COMMITTER_NAME": "a",
           "GIT_COMMITTER_EMAIL": author, "PATH": "/usr/bin:/bin", "HOME": str(root)}
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", message]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, env=who)


def _seal_run_answer(case: tuple) -> None:
    """`sealed_argv` for one tree, against the argv written out above."""
    _kind, root, git_dir, mounts = case
    argv = sealed_argv("registry.example/gate@sha256:ab", root, git_dir, ["pkg/tests/test_one.py"], user="1000:1000")
    script_at = argv.index("bash") + 2
    assert argv[:script_at - 2] == [
        "docker", "run", "--rm", "--network", "none", "--user", "1000:1000", *mounts, "-w", root,
        "registry.example/gate@sha256:ab"]
    assert "uv sync --frozen" in argv[script_at] and "UV_OFFLINE=1" in argv[script_at]
    assert argv[script_at + 1:] == ["sealed", root, *(part.format(root=root) for part in _GATE_PYTEST)]


def _born_answer(root: Path, monkeypatch) -> None:
    """A clock-reading test is refused when this change gives it its first row, and never after."""
    test = "pkg/tests/test_clock.py"
    _write(root, {test: _CLOCK_TEST})
    monkeypatch.setattr(register_main, "ROWS", (_row(test, "pkg"),))
    before, after = root / "before.py", root / "after.py"
    before.write_text("ROWS = ()\n", encoding="utf-8")
    after.write_text(f"ROWS = (Row(test='{test}'),)\n", encoding="utf-8")
    born = register_main._born_unsealed(root, str(before))
    assert [sentence.split(";", 1)[0] for sentence in born] == [
        f"{test} line 2: time.time() reads the wall clock", f"{test} line 3: datetime.now() reads the wall clock",
        f"{test} line 4: date.today() reads the wall clock", f"{test} line 5: time.localtime() reads the wall clock"]
    assert register_main._born_unsealed(root, str(after)) == ()


def _pin_answer(root: Path) -> None:
    """The pin's two fields read back, and the drift named against a scratch history."""
    digest = "registry.example/gate@sha256:" + "a" * 64
    assert read_pin(f"# a comment\n# built from: abc123\n{digest}\n") == Pin(digest, "abc123")
    assert read_pin("# built from:\nregistry.example/gate:latest\n") == Pin("", "")
    _write(root, {"uv.lock": "one\n", "lib/pyproject.toml": "one\n", "docs/notes.txt": "one\n"})
    _commit(root, _PERSON, "built")
    built = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True).stdout.strip()
    _write(root, {"lib/pyproject.toml": "two\n", "docs/notes.txt": "two\n", "infra/gate-image/Dockerfile": "FROM x\n"})
    _commit(root, _PERSON, "moved")
    assert pin_drift(root, built) == ("infra/gate-image/Dockerfile", "lib/pyproject.toml")
    assert pin_drift(root, "") == ()


def _owner_answer() -> None:
    """Who is told, and what, read off `_PROJECT` by hand."""
    assert [owner_login(name, _PROJECT) for name in ("sam", "lee-login", "")] == [
        "sam-login", "lee-login", "owner-login"]
    issue = quarantine_issue("web/tests/test_x.py", "sam-login", _PROJECT, commit="c0ffee", reason="flips",
                             failures=("FAILED web/tests/test_x.py::test_x - assert 1 == 2",))
    assert (issue["title"], issue["assignee"], issue["labels"], issue["parent"]) == (
        "test: test_x.py is quarantined", "sam-login", ["bug", "area:web"], 7)
    assert "FAILED web/tests/test_x.py::test_x" in issue["body"] and "quarantined=" in issue["body"]
    assert quarantine_issue("docs/test_y.py", "", _PROJECT, commit="c", reason="r")["labels"] == ["bug", "area:web"]
    assert quarantine_note((("12", "web/tests/test_x.py"), ("", "pkg/tests/test_y.py"))) == (
        "quarantined #12 test_x.py, test_y.py")


def _scaffold_answer(root: Path, case: tuple) -> None:
    """What `scaffold` writes into a scratch repository with an empty register."""
    _kind, module, sentence, files, before = case
    _write(root, {_ROWS: _EMPTY_REGISTER, f"{module}/__init__.py": '"""A module."""\n', **before})

    test, _rows = scaffold(module, sentence, root)

    directory = root / test.rsplit("/", 1)[0]
    assert sorted(path.relative_to(root).as_posix() for path in directory.iterdir()) == list(files)
    assert test in files


@pytest.mark.parametrize("case", sorted(_CASES))
def test_the_register_answers_each_scratch_repository_as_written(tmp_path: Path, monkeypatch, case: str) -> None:
    kind = _CASES[case][0]
    if kind == "replay":
        _replay_answer(tmp_path, _CASES[case])
    elif kind == "quarantine":
        _quarantine_answer(tmp_path / "repo", _CASES[case], monkeypatch)
    elif kind == "left-out":
        assert left_out(_CASES[case][1], _CASES[case][2]) == _CASES[case][3]
    elif kind == "owner":
        _owner_answer()
    elif kind == "sealed":
        assert live_reads(_CASES[case][1]) == _CASES[case][2]
    elif kind == "sealed-run":
        _seal_run_answer(_CASES[case])
    elif kind == "born":
        _born_answer(tmp_path, monkeypatch)
    elif kind == "pin":
        _pin_answer(tmp_path / "repo")
    elif kind == "scaffold":
        _scaffold_answer(tmp_path, _CASES[case])
    else:
        _register_answer(tmp_path, _CASES[case])
