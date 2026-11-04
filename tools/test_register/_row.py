"""One test, and everything the machine needs to know about it.

OWNS: the shape of a register row, and its one machine-written field, the
quarantine, as text in `_rows.py` (read from any revision's copy, and added).

DOES NOT OWN: the rows themselves (`_rows.py`), what fires a row
(`gate_scope/select.py` reads `runs_when`), whether a row's break still breaks
anything (`_replay.py`), which tests a gate run leaves out (`_quarantine.py`),
or who is told (`_owner.py`).

THE FIELDS, and why each is here rather than derived.

`test` is the file. It is the key: one row per test file, never per module,
because a module group's test is a file of its own beside its modules' tests.

`pins` is the module or modules the test covers. One name is the ordinary
case; two or more makes it the test of how they fit, and that is the whole
declaration. Nothing derives this: an import closure says which files a test
can reach, which is a wider and different question, and the tests that read
the tree as text import nothing at all.

`runs_when` is the changed-path globs that select this test. Globs, never bare
prefixes: a prefix trigger of a top directory makes every file under it, a
Caddyfile included, select a test that only ever reads `.py` files.

`proved_by` is the break, and it may be `None` only while a test is being
written. `__main__.py --check` refuses a committed row without one.

`owner` is who a quarantined test's issue is assigned to: a name from
`people` in `.claude/project.json`, or a login. Empty means the project's
owner (`_owner.py`).

`quarantined` is the one field the deploy gate writes: `(commit, reason,
issue, since)` when the gate found this test to be the wrong one (it fails on
the last good tree too, or the same commit passes it on a re-run), empty
otherwise. A quarantined test leaves the gate with no time limit; its row and
its file stay, and the gate still fails closed on every other test. The owner
ends it by deleting the `quarantined=` line in the commit that fixes the test;
nothing removes one by itself. The field is read from TEXT with `ast` and never
by import, so any revision's copy can be read.

ONLY THE GATE MAY ADD ONE, and the gate believes only its own. A commit that
broke a test could otherwise quarantine that test in the same commit and ship
green with no issue and no triage. So the gate honours a line only from main's
copy (`gate_quarantines`), and only when the commit that added it was authored
by the gate's own address (`GATE_AUTHOR_EMAIL` in `config/harness.env`); a
line in the tested tree alone is ignored. `quarantines_added` is what `--check`
refuses in a diff any other author makes. An author line can be written by
hand, so this stops the accident and the same-commit shortcut, not a forgery.

FAILURE POLICY. Reading never raises: a copy that does not parse, a git that
cannot answer, or no gate address configured is "nothing quarantined", which
keeps every test in the gate. Writing a quarantine raises ValueError for a test
with no single row, because the gate must not commit a file it did not change.
"""
from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ._break import Break


@dataclass(frozen=True)
class Row:
    """What the register knows about one test file."""

    test: str
    pins: tuple[str, ...]
    runs_when: tuple[str, ...]
    proved_by: Break | None = None
    note: str = ""
    kind: str = field(default="module")
    owner: str = ""
    quarantined: tuple = ()


#: Where the rows live, repository-relative.
ROWS_FILE = "tools/test_register/_rows.py"

#: The setting naming the address the gate commits a quarantine as.
GATE_AUTHOR_SETTING = "GATE_AUTHOR_EMAIL"


def quarantined_in(text: str) -> tuple[str, ...]:
    """The test of every row carrying `quarantined=` in one copy of `_rows.py`."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return ()
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Row"):
            continue
        fields = {keyword.arg: keyword.value for keyword in node.keywords}
        test, state = fields.get("test"), fields.get("quarantined")
        if isinstance(test, ast.Constant) and state is not None and _non_empty(state):
            found.append(test.value)
    return tuple(found)


def quarantined_tests(repo: Path) -> tuple[str, ...]:
    """Every test `repo`'s own copy of the rows marks quarantined, sorted."""
    return tuple(sorted(set(quarantined_in(_read(repo / ROWS_FILE)))))


def quarantines_added(base: str, text: str) -> tuple[str, ...]:
    """The tests `text` quarantines that `base`, the copy before it, did not."""
    return tuple(sorted(set(quarantined_in(text)) - set(quarantined_in(base))))


def gate_author() -> str:
    """The gate's commit address, read from the environment at call time; empty when unset."""
    return os.environ.get(GATE_AUTHOR_SETTING, "").strip().lower()


def gate_quarantines(repo: Path, revision: str = "HEAD", author: str | None = None) -> tuple[str, ...]:
    """The quarantines the gate honours: in `revision`'s rows, added by the gate's own address.

    The commit that added a test's `quarantined=` line is the newest commit that
    changed how often that exact line occurs in the rows (`git log -S`). A line
    git cannot place, a repository without history, no gate address, or another
    author: not honoured, so the test stays in the gate.
    """
    expected = (gate_author() if author is None else author).strip().lower()
    if not expected:
        return ()
    text = _git(repo, "show", f"{revision}:{ROWS_FILE}")
    honoured = []
    for test in quarantined_in(text):
        line = _quarantine_line(text, test)
        if not line:
            continue
        added_by = _git(repo, "log", "-1", "--format=%ae", f"-S{line}", revision, "--", ROWS_FILE)
        if added_by.strip().lower() == expected:
            honoured.append(test)
    return tuple(sorted(honoured))


def with_quarantine(text: str, test: str, commit: str, reason: str, issue: str, since: str) -> str:
    """`_rows.py` again with `test`'s row quarantined; unchanged when it already is.

    The field goes on the line after the row's `test=` line, so the owner's fix
    is deleting one line. A test with no row, or written twice, is a ValueError.
    """
    if test in quarantined_in(text):
        return text
    anchors = [anchor for anchor in _anchors(test) if anchor in text]
    if len(anchors) != 1 or text.count(anchors[0]) != 1:
        raise ValueError(f"{test} has no single row to quarantine")
    state = (commit, reason, str(issue), since)
    return text.replace(anchors[0], f"{anchors[0]}        quarantined={state!r},\n", 1)


def _anchors(test: str) -> tuple[str, str]:
    """A row's `test=` line, in either quote style the register is written in."""
    return (f'        test="{test}",\n', f"        test='{test}',\n")


def _quarantine_line(text: str, test: str) -> str:
    """The `quarantined=` line of `test`'s row, stripped; empty when there is none."""
    lines = text.splitlines()
    wanted = {anchor.strip() for anchor in _anchors(test)}
    for index, line in enumerate(lines):
        if line.strip() in wanted:
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            return following if following.startswith("quarantined=") else ""
    return ""


def _git(repo: Path, *argv: str) -> str:
    """One git answer as text; empty when git cannot give it."""
    try:
        done = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True,
                              check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _non_empty(node: ast.AST) -> bool:
    try:
        return bool(ast.literal_eval(node))
    except (ValueError, SyntaxError):
        return True


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
