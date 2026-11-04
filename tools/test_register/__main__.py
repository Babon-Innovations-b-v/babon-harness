"""The register's command line: check it, replay a break, add a test, count the gap, quarantine.

OWNS: turning the things the register can do into exit codes the shell can
read.

DOES NOT OWN: any of them (`_check.py`, `_replay.py`, `birth/`,
`_coverage.py`, `_row.py`, `_quarantine.py`, `_owner.py`).

The verbs, exactly one per run:

  --check [--base F --author E]
                             the register and the tree agree. rc 1 on any
                             disagreement, with every problem printed, not
                             just the first. With `--base` (the rows before
                             this change) and `--author` (its author's email),
                             a `quarantined=` line added by anyone but the
                             gate is refused too, and so is a python test this
                             change gives its first row when it reads the live
                             machine, the clock or the network (`birth/_scan.py`).
  --replay <path>...         apply each named row's break, run its test, demand
                             red. rc 1 when a test passes with its own break
                             applied. `--changed-file` replays every row a
                             commit touches instead of a named list.
  --new <module> --says "…"  write the test file and its row together.
  --coverage                 how many modules the register pins, and which it
                             does not. Never a non-zero exit: it is a number,
                             not a verdict.
  --quarantined [--revision R]
                             every quarantine the gate honours, one per line:
                             in R's rows (default HEAD), added by the gate's
                             own address (`GATE_AUTHOR_EMAIL`).
  --quarantine <test> --commit <sha> --reason "…" --issue <n> --since <date> [--from F]
                             mark one row quarantined. With `--from` (a copy
                             of `_rows.py`) the new file is printed for the
                             gate to commit; without, `--repo`'s copy is
                             rewritten. rc 2 for a test with no single row.
  --left-out <paths file>    the selection with the honoured quarantines taken
                             out: `run <path>`, `ignore <path>`, and `emptied`
                             when the quarantine removed every path.
  --owner <test>             the login a quarantined test's issue goes to.
  --sealed-run <test>...     run the files in the pinned gate image with the
                             network off and a fake clock (`birth/_run.py`).
                             pytest's own exit code, or 99 when this box could
                             not run it, which is never a verdict.
  --pin-drift                the gate image inputs that moved past the commit
                             the pinned image was built from, one per line.
                             Never a non-zero exit: it is a notice.
  --quarantine-issue <test> --commit <sha> --reason "…" [--failures F]
                             the issue for one quarantined test, as JSON.

FAILURE POLICY. `--check` and `--replay` are verdicts and say no by exiting 1.
Everything they cannot do is exit 0 with a note on stderr, the same fail-open
rule the pre-commit hook follows for a missing `uv`: a box without a runner
has not found a problem, it has found a box.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._check import check
from ._coverage import uncovered
from ._debt import DEBT, FUNCTION_DEBT
from ._modules import modules_in
from ._owner import owner_login, quarantine_issue
from ._quarantine import left_out
from ._row import ROWS_FILE, gate_author, gate_quarantines, quarantined_tests, quarantines_added, with_quarantine
from ._replay import GREEN, replay
from ._rows import ROWS
from .birth import PIN, live_reads, pin_drift, read_pin, scaffold, sealed_run
from ._touched import touched_by


def main(argv: list[str] | None = None) -> int:
    """Run one verb. Returns the process exit code."""
    parsed = _parse(argv)
    repo = Path(parsed.repo).resolve()

    if parsed.check:
        return _do_check(repo, parsed.base, parsed.author)
    if parsed.coverage:
        return _do_coverage(repo)
    if parsed.new:
        return _do_new(repo, parsed.new, parsed.says)
    if parsed.quarantined:
        print("\n".join(gate_quarantines(repo, parsed.revision)))
        return 0
    if parsed.quarantine:
        return _do_quarantine(repo, parsed)
    if parsed.left_out:
        return _do_left_out(repo, parsed.left_out, parsed.revision)
    if parsed.owner:
        print(owner_login(_owner_of(parsed.owner), _project(repo)))
        return 0
    if parsed.quarantine_issue:
        return _do_quarantine_issue(repo, parsed)
    if parsed.sealed_run is not None:
        return sealed_run(repo, parsed.sealed_run)
    if parsed.pin_drift:
        return _do_pin_drift(repo)
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
    parser.add_argument("--base", default="", metavar="FILE", help="with --check: the rows before this change")
    parser.add_argument("--author", default="", metavar="EMAIL", help="with --check: who made this change")
    parser.add_argument("--quarantined", action="store_true", help="list the quarantines the gate honours")
    parser.add_argument("--revision", default="HEAD", metavar="REV", help="whose rows the gate reads")
    parser.add_argument("--quarantine", default="", metavar="TEST")
    parser.add_argument("--commit", default="", metavar="SHA")
    parser.add_argument("--reason", default="", metavar="WORDS")
    parser.add_argument("--issue", default="", metavar="N")
    parser.add_argument("--since", default="", metavar="DATE")
    parser.add_argument("--from", dest="source", default="", metavar="FILE")
    parser.add_argument("--left-out", default="", metavar="PATHS_FILE")
    parser.add_argument("--owner", default="", metavar="TEST")
    parser.add_argument("--quarantine-issue", default="", metavar="TEST")
    parser.add_argument("--failures", default="", metavar="FILE", help="with --quarantine-issue")
    parser.add_argument("--sealed-run", nargs="+", default=None, metavar="TEST")
    parser.add_argument("--pin-drift", action="store_true", help="gate image inputs past its build")
    parser.add_argument(
        "--allow-missing-break",
        action="store_true",
        help="do not refuse a row that has no break yet (used while writing one)",
    )
    return parser.parse_args(argv)


def _do_check(repo: Path, base: str = "", author: str = "") -> int:
    problems = (
        check(repo, ROWS, debt=DEBT, function_debt=FUNCTION_DEBT)
        + _quarantines_refused(repo, base, author)
        + _born_unsealed(repo, base)
    )
    if not problems:
        print(f"register: {len(ROWS)} rows, and the tree agrees")
        return 0
    for problem in problems:
        print(f"register: {problem}", file=sys.stderr)
    print(
        f"\n{len(problems)} problem(s). Every test in this repository needs a row in\n"
        "tools/test_register/_rows.py saying what it pins, what selects it,\n"
        "and the break that proves it can fail; every module and module group\n"
        "has one test, and every test file holds one test function.",
        file=sys.stderr,
    )
    return 1


def _quarantines_refused(repo: Path, base: str, author: str) -> tuple[str, ...]:
    """A `quarantined=` line this change adds, unless the gate is its author."""
    if not base or not author:
        return ()
    gate = gate_author()
    if gate and author.strip().lower() == gate:
        return ()
    try:
        before = Path(base).read_text(encoding="utf-8")
        current = (repo / ROWS_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    return tuple(
        f"{test} is quarantined by {author}; only the deploy gate adds a `quarantined=` "
        f"line, so remove it and fix the test instead"
        for test in quarantines_added(before, current)
    )


def _born_unsealed(repo: Path, base: str) -> tuple[str, ...]:
    """Every live read in a python test this change gives its first row."""
    if not base:
        return ()
    try:
        before = Path(base).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    problems = []
    for row in ROWS:
        born = f'"{row.test}"' not in before and f"'{row.test}'" not in before
        if not born or not row.test.endswith(".py") or not (repo / row.test).is_file():
            continue
        source = (repo / row.test).read_text(encoding="utf-8", errors="replace")
        problems.extend(
            f"{row.test} {finding}; a new test builds its own input and answer (a synthetic "
            f"ground truth) and never reads the live machine, the clock or the network"
            for finding in live_reads(source)
        )
    return tuple(problems)


def _do_pin_drift(repo: Path) -> int:
    """Print every gate image input that moved past the pinned image's build."""
    try:
        pin = read_pin((repo / PIN).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        print(f"register: no gate image pin at {PIN}", file=sys.stderr)
        return 0
    for moved in pin_drift(repo, pin.built_from):
        print(moved)
    return 0


def _do_quarantine(repo: Path, parsed: argparse.Namespace) -> int:
    """Mark one row quarantined; print the file or rewrite `repo`'s copy."""
    test = parsed.quarantine
    source = Path(parsed.source) if parsed.source else repo / ROWS_FILE
    try:
        text = source.read_text(encoding="utf-8")
        written = with_quarantine(text, test, parsed.commit, parsed.reason, parsed.issue, parsed.since)
    except (OSError, ValueError) as refusal:
        print(f"register: cannot quarantine {test}: {refusal}", file=sys.stderr)
        return 2
    if parsed.source:
        sys.stdout.write(written)
        return 0
    source.write_text(written, encoding="utf-8")
    print(f"quarantined {test}")
    return 0


def _do_left_out(repo: Path, paths_file: str, revision: str) -> int:
    """Print what one gate run is given once the honoured quarantines are out."""
    lines = _lines(paths_file)
    if lines is None:
        return 2
    answer = left_out(lines, gate_quarantines(repo, revision))
    for path in answer.paths:
        print(f"run {path}")
    for path in answer.ignores:
        print(f"ignore {path}")
    if answer.emptied:
        print("emptied")
    return 0


def _do_quarantine_issue(repo: Path, parsed: argparse.Namespace) -> int:
    """Print the issue for one quarantined test as JSON."""
    test = parsed.quarantine_issue
    failures = (_lines(parsed.failures) or []) if parsed.failures else []
    project = _project(repo)
    issue = quarantine_issue(test, owner_login(_owner_of(test), project), project,
                             commit=parsed.commit, reason=parsed.reason, failures=failures)
    print(json.dumps(issue))
    return 0


def _owner_of(test: str) -> str:
    """The `owner` a test's row names, empty when it names nobody or has no row."""
    return next((row.owner for row in ROWS if row.test == test and row.owner), "")


def _project(repo: Path) -> dict:
    """`.claude/project.json`, or an empty project when it cannot be read."""
    try:
        return json.loads((repo / ".claude/project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _lines(path: str) -> list[str] | None:
    """The non-empty lines of a file, `-` for stdin; None (said on stderr) when it cannot be read."""
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        print(f"register: cannot read {path}: {failure}", file=sys.stderr)
        return None
    return [line.strip() for line in text.splitlines() if line.strip()]


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
    """Replay every named row's break, quarantined tests left out. Only a `green` refuses."""
    out = set(quarantined_tests(repo))
    rows = tuple(row for row in _rows_to_replay(repo, named, changed_file) if row.test not in out)
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
