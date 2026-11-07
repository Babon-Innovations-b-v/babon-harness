"""Refuse a push to main whose tip breaks the test register or a test the push reaches.

WHY (the 2026-11-07 retro). The pre-commit checks only what one commit stages:
a module edited without its test reached the deploy gate with no local run of
that test, and a commit made with the hooks off, or in a checkout whose
core.hooksPath was never set, reached it with nothing checked at all. The push
is the last place a session can still fix a red before the gate judges it.

WHAT IT RUNS, for each pushed ref to refs/heads/main whose tip is this
checkout's HEAD (the usual `git push origin HEAD:main`):

1. `test_register --check`: the tree and the register agree (one test a file,
   one per level, every debt list only shrinking, every row's break written).
2. The test files of every row the push touches (`touched_by` over the paths
   the push changes against what main already has: the test, the module it
   pins, or the file its break edits), sealed in the gate image, or with this
   box's own pytest when it cannot run that image (exit 99), bounded at
   `PUSH_GATE_SECONDS`.

It checks the tip only. The gate still judges every commit on its own tree.

A RED MAIN ALREADY HAD IS NOT THIS PUSH'S. When a step says no, the same step
runs again on a scratch worktree of what main had; a register problem main
already shows, or a test file that fails there too, does not refuse the push
(the gate ejects the commit that made it). Only what this push adds refuses.

FAILURE POLICY: fail open on everything it cannot do. A tip that is not HEAD,
no git, a register that crashed, no pytest, a run past its bound, a usage error
or an empty collection: the push goes, with one line on stderr. Only a check
that RAN and said no exits 1. `git push --no-verify` is the human's waiver.
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REGISTER = "tools.test_register"
SECONDS = int(os.environ.get("PUSH_GATE_SECONDS", "300"))
_ZERO = "0" * 40
#: The sealed run's own answer when this box cannot run the gate image.
_CANNOT = 99
#: Git's own variables, stripped for every child: a hook's children inherit
#: GIT_DIR, which overrides cwd, so a test building a scratch repository in
#: tmp_path would otherwise write into the repository being pushed.
_GIT_VARS = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_INDEX_VERSION",
             "GIT_QUARANTINE_PATH")


def pushed_tips(lines) -> list[tuple[str, str]]:
    """(tip, what main had) for every pushed line that updates refs/heads/main."""
    tips = []
    for line in lines:
        parts = line.split()
        if len(parts) == 4 and parts[2] == "refs/heads/main" and parts[1] != _ZERO:
            tips.append((parts[1], parts[3]))
    return tips


def refusal(step: str, verdict: int, output: str) -> str | None:
    """The refusal for one step's exit code, or None when it said yes or could not say."""
    if step == "register":
        said_no = verdict == 1 and "Traceback" not in output
    else:
        said_no = verdict in (1, 2, 3)
    if not said_no:
        return None
    return f"BLOCKED: the {step} check said no on the tip this push puts on main.\n{_tail(output)}"


def _tail(output: str, lines: int = 40) -> str:
    return "\n".join(output.splitlines()[-lines:])


def _env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _GIT_VARS}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False,
                          env=_env())


def _run(root: Path, argv: list[str]) -> tuple[int, str]:
    """One bounded command in the root; 124 when it ran past its bound."""
    try:
        done = subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False, timeout=SECONDS,
                              env={**_env(), "PYTHONPATH": str(root)})
    except subprocess.TimeoutExpired:
        return 124, f"stopped after {SECONDS} s"
    except OSError as error:
        return 127, str(error)
    return done.returncode, done.stdout + done.stderr


def changed_paths(root: Path, tip: str, had: str) -> list[str]:
    """The paths the push changes against what main already has (its merge base with origin/main if unknown)."""
    base = had
    if had == _ZERO or _git(root, "cat-file", "-e", f"{had}^{{commit}}").returncode:
        base = _git(root, "merge-base", "origin/main", tip).stdout.strip()
    if not base:
        return []
    return [path for path in _git(root, "diff", "--name-only", base, tip).stdout.splitlines() if path]


def touched_tests(root: Path, changed: list[str]) -> list[str]:
    """The test files of every register row the changed paths reach, those in the tree (the root on PYTHONPATH)."""
    register = importlib.import_module(REGISTER)
    return sorted({row.test for row in register.touched_by(changed, register.ROWS) if (root / row.test).is_file()})


def run_tests(root: Path, tests: list[str]) -> tuple[int, str]:
    """The tests sealed in the gate image, or with this box's pytest when it cannot run that image."""
    verdict, output = _run(root, [sys.executable, "-m", REGISTER, "--repo", str(root), "--sealed-run", *tests])
    if verdict != _CANNOT:
        return verdict, output
    python_tests = [test for test in tests if test.endswith(".py")]
    if not python_tests:
        return _CANNOT, output
    print("push gate: the gate image cannot run here, so the touched tests run with this box's pytest",
          file=sys.stderr)
    runner = ["uv", "run", "--frozen", "python"] if (root / "uv.lock").is_file() else [sys.executable]
    return _run(root, [*runner, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly",
                       "-p", "no:cacheprovider", *python_tests])


def register_check(root: Path) -> tuple[int, str]:
    """`test_register --check` on one tree."""
    return _run(root, [sys.executable, "-m", REGISTER, "--check", "--repo", str(root)])


def failed_files(output: str) -> set[str]:
    """The test files pytest's summary names as FAILED or ERROR."""
    return set(re.findall(r"^(?:FAILED|ERROR) ([^\s:]+)", output, re.MULTILINE))


def new_reds(step: str, pushed: str, mains: str) -> set[str]:
    """What the pushed run says no to that main's run of the same step does not."""
    if step == "register":
        return {line for line in pushed.splitlines() if line.strip()} - set(mains.splitlines())
    return failed_files(pushed) - failed_files(mains)


def on_main(root: Path, had: str, run) -> tuple[int, str] | None:
    """`run` on a scratch worktree of what main had, or None when that tree cannot be made."""
    if had == _ZERO:
        return None
    scratch = Path(tempfile.mkdtemp(prefix="push-gate-main-"))
    tree = scratch / "main"
    try:
        if _git(root, "worktree", "add", "--detach", "-q", str(tree), had).returncode:
            return None
        return run(tree)
    finally:
        _git(root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(scratch, ignore_errors=True)


def judged(root: Path, had: str, step: str, verdict: int, output: str, run) -> str | None:
    """The refusal for one step's run, unless main had every red it found."""
    said = refusal(step, verdict, output)
    if not said:
        return None
    mains = on_main(root, had, run)
    if mains is None or (step != "register" and mains[0] not in (0, 1, 2, 3)):
        return said
    if not new_reds(step, output, mains[1]):
        print(f"push gate: the {step} check is red on main already, not by this push; it goes", file=sys.stderr)
        return None
    return said


def check_tip(root: Path, tip: str, had: str) -> str | None:
    """The refusal for one pushed tip, or None when it may go."""
    verdict, output = register_check(root)
    said = judged(root, had, "register", verdict, output, register_check)
    if said:
        return said
    if verdict and not refusal("register", verdict, output):
        print(f"push gate: the register check could not run (exit {verdict})", file=sys.stderr)
    tests = touched_tests(root, changed_paths(root, tip, had))
    if not tests:
        return None
    verdict, output = run_tests(root, tests)
    if verdict not in (0, 1, 2, 3):
        print(f"push gate: the {len(tests)} touched test file(s) gave no verdict (exit {verdict})", file=sys.stderr)
    return judged(root, had, "touched tests", verdict, output, lambda tree: run_tests(tree, tests))


def main(stdin=sys.stdin) -> int:
    root_said = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if root_said.returncode:
        return 0
    root = Path(root_said.stdout.strip())
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    for tip, had in pushed_tips(stdin):
        if tip != head:
            print(f"push gate: {tip[:10]} is not this checkout's HEAD, so it was not checked here",
                  file=sys.stderr)
            continue
        said = check_tip(root, tip, had)
        if said:
            print(said, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
