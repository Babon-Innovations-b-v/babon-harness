"""Sort one red from the shell: `python3 -m tools.red_triage < answers.json`.

OWNS: reading the three runs' answers as JSON on stdin and printing the
verdict in lines a shell step reads.

DOES NOT OWN: the rule (`_triage.py`).

INPUT, one JSON object: `failing` (the red run's failing test files),
`rerun_failing` and `good_failing` (lists, or null for a run that could not
run), and `new_files` (the files the last good tree lacks or this commit
changed).

OUTPUT: the kind (`commit`, `test` or `setup`) on the first line, then one
`quarantine<TAB><test><TAB><reason>` line per test that leaves the gate.

FAILURE POLICY. Input that is not that object exits 2 with the reason on
stderr and prints no kind, so the caller treats it as a run that could not be
sorted (amber), never as a verdict.
"""
from __future__ import annotations

import json
import sys

from ._triage import triage


def main() -> int:
    """Read one red's answers, print its triage. Returns the exit code."""
    try:
        answers = json.loads(sys.stdin.read())
        verdict = triage(
            frozenset(answers["failing"]),
            _maybe(answers.get("rerun_failing")),
            _maybe(answers.get("good_failing")),
            frozenset(answers.get("new_files") or ()),
        )
    except (ValueError, KeyError, TypeError) as failure:
        print(f"red_triage: cannot read the answers: {failure!r}", file=sys.stderr)
        return 2
    print(verdict.kind)
    for test, reason in verdict.quarantine:
        print(f"quarantine\t{test}\t{reason}")
    return 0


def _maybe(files: list | None) -> frozenset[str] | None:
    """A run's failing files, or None for a run that could not run."""
    return None if files is None else frozenset(files)


if __name__ == "__main__":
    raise SystemExit(main())
