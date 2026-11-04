"""Apply a row's break, run its test, demand red, put the file back.

OWNS: proving that one test can fail, right now, on this tree.

DOES NOT OWN: which rows to replay (`__main__.py` decides that from the
changed paths), or what a row is (`_row.py`).

SEVERAL AT ONCE. `replay_all` spreads the rows over workers, each on its own
copy of the tree, because one row breaks one file and two rows at once in one
tree would each see the other's break. A copy is hard links, so making six
costs seconds rather than six times the tree; `replay` therefore never writes
into a file in place, it unlinks it first, so a break lands in the copy alone.
A `green` from a copy refuses nothing until the same row is replayed in the
tree itself and says `green` again: a verdict that refuses a commit is only
taken from the commit's own tree.

A copy that cannot be made, or a worker that raises, is a fault of the box and
never a verdict: the rows are then replayed one at a time in the tree itself.
`replay` can still raise when the tree itself will not take the break or the
file back (an unreadable encoding, a read-only directory); the command line
reads that as "could not finish" and never as a refusal.

WHY THIS EXISTS AT ALL. A test that can never fail looks exactly like a good
one: it is green, it is named for an invariant, and it verifies nothing. Break
the code on purpose, watch the test go red, put the code back: this file does
that by machine, from the break written down in the test's row.

THREE VERDICTS, the same three the deploy gate itself uses, and for the same
reason. The file is restored in a `finally`, byte for byte, from the bytes read
before the edit; a replay that crashes leaves nothing behind. The verdict is
data, never an exception:

  `red`       the test failed with the break applied, which is what proves it
              can fail. This is the pass.
  `green`     the test PASSED with its own break applied, so it does not check
              what its row claims. This is the finding this file exists to
              make, and it is the only one that refuses a commit.
  `unproven`  nothing could be concluded: the anchor was missing or ambiguous,
              the runner is not on this box, the run was refused, it hit its
              bound, or every test in the file SKIPPED.

The last one is easy to get wrong. pytest exits 0 when everything skips, so a
file that skips for want of a tool reads exactly like a file that passed with
the break applied, which would report a test as unfalsifiable when nothing had
run at all. `unproven` is deliberately not a refusal: a missing runner is a
note, never proof.

A SKIP ANYWHERE IN THE FILE MAKES THE RUN UNPROVEN, not green. A skipped case
may be the one the break was aimed at, while another case passes regardless.

PUTTING THE FILE BACK IS NOT ENOUGH. The run compiles the broken source into
`__pycache__`, the bytes are restored, and the next interpreter can load the
cached broken code. So the run is told not to write bytecode at all, and any
cached copy is removed after the restore. A replay leaves nothing behind.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ._row import Row

#: The three verdicts, named the way the deploy gate names its own.
RED = "red"
GREEN = "green"
UNPROVEN = "unproven"

#: How long one replayed test may take before it is stopped. A module test is
#: seconds; this is the runaway bound, not a budget.
TIMEOUT_SECONDS = 300

#: pytest's own exit codes. Only 1 is a failing test; 2 to 5 are the run
#: refusing, which says nothing about whether the break works.
_PYTEST_FAILED = 1
_PYTEST_REFUSED = frozenset({2, 3, 4, 5})


def replay(
    row: Row, repo: Path, run: Callable[[Row, Path], int] | None = None
) -> tuple[str, str]:
    """Break the module, run the test, demand red, restore.

    Raises only when the tree will not take the break or its bytes back; every
    answer about the test itself is a verdict.

    Returns one of `red`, `green` or `unproven`, and the sentence that goes in
    the report beside it.
    """
    if row.proved_by is None:
        return UNPROVEN, f"{row.test} has no break recorded, so nothing was proved"

    target = repo / row.proved_by.file
    try:
        before = target.read_bytes()
    except OSError as failure:
        return UNPROVEN, f"cannot read {row.proved_by.file}: {failure}"

    text = before.decode("utf-8")
    hits = text.count(row.proved_by.old)
    if hits != 1:
        return UNPROVEN, (
            f"{row.test}: the break anchor appears {hits} times in "
            f"{row.proved_by.file}; it must appear exactly once, so nothing was applied"
        )

    runner = run or _default_runner
    mode = target.stat().st_mode
    try:
        # Unlinked first: in a worker's copy the file is a hard link to the
        # tree's own, and writing through it would break the tree as well.
        target.unlink()
        target.write_bytes(text.replace(row.proved_by.old, row.proved_by.new).encode("utf-8"))
        os.chmod(target, mode)
        verdict = runner(row, repo)
    finally:
        target.write_bytes(before)
        os.chmod(target, mode)
        _forget_bytecode(target)

    return _read(row, verdict)


def replay_all(
    rows: tuple, repo: Path, workers: int = 1, run: Callable[[Row, Path], int] | None = None
) -> list[tuple[str, str]]:
    """Every row's verdict and sentence, in row order, `workers` rows at a time.

    Copies that cannot be made, or a worker that raises, fall back to one row at
    a time in the tree itself: a full disk is not a finding about any test.
    """
    count = min(max(workers, 1), len(rows))
    if count <= 1:
        return [replay(row, repo, run) for row in rows]
    try:
        answers = _replay_in_copies(rows, repo, count, run)
    except Exception as failure:  # noqa: BLE001  any fault of the copies is the box's, never a verdict
        print(f"register: replaying on {count} copies of the tree failed ({failure!r}); "
              "replaying one row at a time in the tree itself", file=sys.stderr)
        return [replay(row, repo, run) for row in rows]
    return [replay(row, repo, run) if verdict == GREEN else (verdict, sentence)
            for row, (verdict, sentence) in zip(rows, answers)]


def _replay_in_copies(
    rows: tuple, repo: Path, count: int, run: Callable[[Row, Path], int] | None
) -> list[tuple[str, str]]:
    """Every row's verdict on `count` linked copies of the tree, the copies removed after."""
    scratch = Path(tempfile.mkdtemp(prefix=".replay-", dir=repo.resolve().parent))
    try:
        copies: queue.Queue = queue.Queue()
        for index in range(count):
            copy = scratch / str(index)
            _link_tree(repo, copy)
            copies.put(copy)

        def _one(row: Row) -> tuple[str, str]:
            copy = copies.get()
            try:
                return replay(row, copy, run)
            finally:
                copies.put(copy)

        with ThreadPoolExecutor(count) as pool:
            answers = list(pool.map(_one, rows))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return answers


def _link_tree(source: Path, copy: Path) -> None:
    """A copy of the tree whose files are hard links, or real copies where a link cannot be made."""
    def _link(src: str, dst: str) -> None:
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)

    # A virtualenv inside the tree is the runner, not the tree: tests run on
    # `sys.executable`, and linking its tens of thousands of files is most of
    # the copy on a dev box.
    shutil.copytree(source, copy, symlinks=True, copy_function=_link,
                    ignore=shutil.ignore_patterns(".venv"))


def _forget_bytecode(source: Path) -> None:
    """Remove any bytecode compiled while the break was applied.

    Best-effort by design: a cache that is not there, or that this process may
    not delete, is not a reason to fail a replay whose verdict is already in.
    """
    cache = source.parent / "__pycache__"
    if not cache.is_dir():
        return
    for compiled in cache.glob(f"{source.stem}.*.pyc"):
        try:
            compiled.unlink()
        except OSError:
            pass


def _read(row: Row, verdict: int) -> tuple[str, str]:
    """Turn one runner exit code into a verdict and the sentence beside it."""
    if verdict == _PYTEST_FAILED:
        return RED, f"{row.test} went red on its break, as it should"
    if verdict == 0:
        return GREEN, (
            f"{row.test} PASSED with its own break applied, so it does not check "
            f"what its row claims: {row.proved_by.why}"
        )
    if verdict == _TIMED_OUT:
        return UNPROVEN, f"{row.test} ran past {TIMEOUT_SECONDS}s and was stopped"
    if verdict == _NO_RUNNER:
        return UNPROVEN, f"no runner for {row.test} on this box, so nothing was proved"
    if verdict == _NOTHING_RAN:
        return UNPROVEN, (
            f"{row.test} skipped everything on this box, so nothing was proved. "
            "A skip is a test saying it knows where it is, not one that cannot fail."
        )
    if verdict == _SOMETHING_SKIPPED:
        return UNPROVEN, (
            f"{row.test} passed with its break applied, but part of it skipped on "
            "this box, and the skipped part may be the half the break was aimed "
            "at. Run it where nothing skips before believing it checks nothing."
        )
    if verdict in _PYTEST_REFUSED:
        return UNPROVEN, f"{row.test}: the run refused (exit {verdict}), so nothing was proved"
    return RED, f"{row.test} failed (exit {verdict}) on its break"


#: Sentinels the default runner returns for the three things that are not a
#: verdict about the test. Chosen outside pytest's 0-5 range so they cannot be
#: confused with one.
_TIMED_OUT = 124
_NOTHING_RAN = 125
_SOMETHING_SKIPPED = 126
_NO_RUNNER = 127

#: pytest's summary counts a passing test only when one actually ran. A file
#: where everything skipped prints "3 skipped" and exits 0.
#:
#: No `\b` in front of the digit: pytest colours its summary, and the escape
#: sequence before the count ends in `m`, a word character, so there is no word
#: boundary to match. The run is also asked for plain output below.
_PASSED_ANY = re.compile(r"(?<![0-9])\d+ passed")

#: Any case in the file that did not run its assertions: skipped, expected to
#: fail, or deselected. Each can hide the case the break was aimed at, so a run
#: carrying one cannot say the test survived it. Erring here costs nothing:
#: `unproven` blocks no commit, and a false `green` reverts one.
_SKIPPED_ANY = re.compile(r"(?<![0-9])\d+ (?:skipped|xfailed|deselected)")

#: What the interpreter prints when it has no pytest. It exits 1, the same code
#: as a failing test, and read as one it would report proof while nothing ran.
_NO_PYTEST = re.compile(r"No module named pytest\s*$")


def _default_runner(row: Row, repo: Path) -> int:
    """Run one test file the way the gate runs it."""
    return _run_pytest(row, repo)


def _run_pytest(row: Row, repo: Path) -> int:
    """One pytest file, quiet, with the plugin that shuffles order turned off."""
    verdict, output = _run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly", row.test],
        repo,
    )
    if _NO_PYTEST.search(output):
        return _NO_RUNNER
    if verdict != 0:
        return verdict
    if not _PASSED_ANY.search(output):
        return _NOTHING_RAN
    if _SKIPPED_ANY.search(output):
        return _SOMETHING_SKIPPED
    return verdict


def _run(argv: list[str], cwd: Path) -> tuple[int, str]:
    """Run one command, bounded, swallowing only what is not a verdict.

    `PYTHONDONTWRITEBYTECODE` so the broken source is never cached in the first
    place; `_forget_bytecode` clears what an earlier run may have left.
    """
    try:
        finished = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1",
                 # The tree being replayed first, so a worker's copy imports
                 # its own broken module and not the tree's.
                 "PYTHONPATH": os.pathsep.join(
                     part for part in (str(cwd), os.environ.get("PYTHONPATH", "")) if part)},
        )
    except subprocess.TimeoutExpired:
        return _TIMED_OUT, ""
    except (OSError, ValueError):
        return _NO_RUNNER, ""
    return finished.returncode, f"{finished.stdout}\n{finished.stderr}"
