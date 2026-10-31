"""The register's command line: check it, replay a break, add a test, count the gap.

OWNS: turning the four things the register can do into exit codes the shell can
read.

DOES NOT OWN: any of the four (`_check.py`, `_replay.py`, `_scaffold.py`,
`_coverage.py`).

Four verbs, and exactly one per run:

  --check                    the register and the tree agree. rc 1 on any
                             disagreement, with every problem printed, not
                             just the first.
  --replay <path>...         apply each named row's break, run its test, demand
                             red. rc 1 when a test passes with its own break
                             applied. `--changed-file` replays every row a
                             commit touches instead of a named list.
  --new <module> --says "…"  write the test file and its row together.
  --coverage                 how many modules the register pins, and which it
                             does not. Never a non-zero exit: it is a number,
                             not a verdict.

FAILURE POLICY. `--check` and `--replay` are verdicts and say no by exiting 1.
Everything they cannot do is exit 0 with a note on stderr, the same fail-open
rule the pre-commit hook follows for a missing `uv`: a box without a runner
has not found a problem, it has found a box.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._check import check
from ._coverage import uncovered
from ._modules import modules_in
from ._replay import GREEN, replay
from ._rows import ROWS
from ._scaffold import scaffold
from ._touched import touched_by


def main(argv: list[str] | None = None) -> int:
    """Run one verb. Returns the process exit code."""
    parsed = _parse(argv)
    repo = Path(parsed.repo).resolve()

    if parsed.check:
        return _do_check(repo)
    if parsed.coverage:
        return _do_coverage(repo)
    if parsed.new:
        return _do_new(repo, parsed.new, parsed.says)
    return _do_replay(repo, parsed.replay, parsed.changed_file)


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m tools.test_register")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--check", action="store_true", help="register against tree")
    parser.add_argument("--coverage", action="store_true", help="count the gap")
    parser.add_argument("--replay", nargs="*", default=None, metavar="TEST")
    parser.add_argument("--changed-file", default="", metavar="FILE")
    parser.add_argument("--new", default="", metavar="MODULE")
    parser.add_argument("--says", default="", metavar="SENTENCE")
    parser.add_argument(
        "--allow-missing-break",
        action="store_true",
        help="do not refuse a row that has no break yet (used while writing one)",
    )
    return parser.parse_args(argv)


def _do_check(repo: Path) -> int:
    problems = check(repo, ROWS)
    if not problems:
        print(f"register: {len(ROWS)} rows, and the tree agrees")
        return 0
    for problem in problems:
        print(f"register: {problem}", file=sys.stderr)
    print(
        f"\n{len(problems)} problem(s). Every test in this repository needs a row in\n"
        "tools/test_register/_rows.py saying what it pins, what selects it,\n"
        "and the break that proves it can fail.",
        file=sys.stderr,
    )
    return 1


def _do_coverage(repo: Path) -> int:
    modules = modules_in(repo)
    gaps = uncovered(modules, ROWS)
    covered = len(modules) - len(gaps)
    print(f"modules {len(modules)} | pinned by a row {covered} | no test {len(gaps)}")
    for module in gaps:
        print(f"  no test: {module}")
    return 0


def _do_new(repo: Path, module: str, says: str) -> int:
    if not says:
        print("--new needs --says '<the invariant, in words>'", file=sys.stderr)
        return 2
    try:
        test, rows_file = scaffold(module, says, repo)
    except (ValueError, FileExistsError) as refusal:
        print(f"register: {refusal}", file=sys.stderr)
        return 2
    print(f"wrote {test}\nwrote a row in {rows_file}")
    print("\nFill in both, then prove the break:")
    print(f"  python3 -m tools.test_register --replay {test}")
    return 0


def _do_replay(repo: Path, named: list[str] | None, changed_file: str) -> int:
    """Replay every named row's break. Only a `green` refuses."""
    rows = _rows_to_replay(repo, named, changed_file)
    if not rows:
        print("register: no row to replay")
        return 0

    passed = []
    for row in rows:
        verdict, sentence = replay(row, repo)
        print(f"{verdict:9}{sentence}")
        if verdict == GREEN:
            passed.append(sentence)
    if passed:
        print(
            f"\nBLOCKED: {len(passed)} test(s) passed with their own break applied.\n"
            "A test that cannot fail is not a test: fix the test so it checks what\n"
            "its row claims, or write a break that actually trips it.",
            file=sys.stderr,
        )
        return 1
    return 0


def _rows_to_replay(repo: Path, named: list[str] | None, changed_file: str) -> tuple:
    """The rows one run replays: a named list, or everything a commit touches."""
    if changed_file:
        try:
            changed = [
                line.strip()
                for line in Path(changed_file).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError as failure:
            print(f"register: cannot read {changed_file}: {failure}", file=sys.stderr)
            return ()
        return touched_by(changed, ROWS)
    if named:
        wanted = set(named)
        return tuple(row for row in ROWS if row.test in wanted)
    return ()


if __name__ == "__main__":
    raise SystemExit(main())
