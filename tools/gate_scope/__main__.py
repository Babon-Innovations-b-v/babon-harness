"""CLI seam for the deploy gate: the only place that touches argv and stdout.

    python3 -m tools.gate_scope \
        --changed-file /var/lib/harness/gate-changed-paths \
        --repo /opt/harness/repo \
        --out-paths /var/lib/harness/gate-selected-paths \
        --out-json  /var/lib/harness/gate-scope.json

Contract with `infra/auto-deploy/steps/20-changes.sh`:

  * **stdout** carries exactly one line, the scope word. Nothing else, ever:
    step 20 reads it with a command substitution and any second line makes the
    `case` fall through to its full-gate default.
  * **stderr** is free-form and is appended to the deploy log by the caller.
  * **exit 0** means a decision was made, including a decision of `full`.
    **exit 2** is a crash. `select.decide` catches everything recoverable
    itself, so exit 2 means this file is broken, and step 20 reads it as full.
  * Both output files are truncated to empty for `none` and `full`, so a stale
    selection from a previous cycle can never be handed to pytest.

This runs under the machine's SYSTEM `python3`, never a project venv, so the
decision about what to verify cannot break along with the environment it
verifies. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .select import Decision, decide


def main(argv: list[str] | None = None) -> int:
    """Decide the scope for one commit and print it."""
    parser = argparse.ArgumentParser(prog="gate_scope", description=__doc__)
    parser.add_argument("--changed-file", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out-paths", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    started = time.monotonic()
    changed = _read_changed(Path(args.changed_file))
    decision = decide(changed, repo)
    elapsed = round(time.monotonic() - started, 2)

    _write_outputs(decision, args, repo, elapsed)

    print(
        f"[scope] {decision.scope}: {decision.reason} "
        f"({len(decision.paths)} paths, {elapsed}s)",
        file=sys.stderr,
    )
    print(decision.scope)
    return 0


def _write_outputs(
    decision: Decision, args: argparse.Namespace, repo: Path, elapsed: float
) -> None:
    """Write the path list and the record file, both empty unless `selected`.

    Truncating them for `none` and `full` is what stops a stale selection from a
    previous cycle ever reaching pytest.
    """
    body = ""
    if decision.scope == "selected":
        body = "\n".join(decision.paths) + "\n"
    _write_atomic(Path(args.out_paths), body)

    record = ""
    if decision.scope == "selected":
        record = json.dumps(
            {
                "sha": _head(repo),
                "scope": decision.scope,
                "reason": decision.reason,
                "paths": list(decision.paths),
                "counts": dict(decision.counts),
                "selector_seconds": elapsed,
            }
        )
    _write_atomic(Path(args.out_json), record)


def _read_changed(path: Path) -> list[str]:
    """One repo-relative path per line, written by step 20 without re-splitting."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _head(repo: Path) -> str:
    """The SHA the decision was made against, for the record file."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return done.stdout.strip()


def _write_atomic(path: Path, body: str) -> None:
    """Write through a sibling `.tmp` so a half-written list is never read."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as failure:  # noqa: BLE001, exit 2 is the contract
        print(f"[scope] selector crashed: {failure!r}", file=sys.stderr)
        raise SystemExit(2) from failure
