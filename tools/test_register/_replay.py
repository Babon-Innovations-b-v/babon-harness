"""Apply a row's break, run its test, demand red, put the file back.

OWNS: proving that one test can fail, right now, on this tree.

DOES NOT OWN: which rows to replay (`__main__.py` decides that from the
changed paths), or what a row is (`_row.py`).

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
import re
import subprocess
import sys
from collections.abc import Callable
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
    """Break the module, run the test, demand red, restore. Never raises.

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
    try:
        target.write_bytes(text.replace(row.proved_by.old, row.proved_by.new).encode("utf-8"))
        verdict = runner(row, repo)
    finally:
        target.write_bytes(before)
        _forget_bytecode(target)

    return _read(row, verdict)


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


def _default_runner(row: Row, repo: Path) -> int:
    """Run one test file the way the gate runs it."""
    return _run_pytest(row, repo)


def _run_pytest(row: Row, repo: Path) -> int:
    """One pytest file, quiet, with the plugin that shuffles order turned off."""
    verdict, output = _run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly", row.test],
        repo,
    )
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
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return _TIMED_OUT, ""
    except (OSError, ValueError):
        return _NO_RUNNER, ""
    return finished.returncode, f"{finished.stdout}\n{finished.stderr}"
