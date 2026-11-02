"""Refuse a push to main while the deploy queue is already long.

WHY. The deploy server checks every commit on its own and moves the deploy one
commit per run, so the queue drains one commit per run when every commit is
green, and stops dead at the first red one. A session that pushes one commit
per bug, from several parallel fix agents, jams it for hours. So bigger pieces
of work go in: a bug fix with its test is one commit; a session's batch of
fixes on one subject is one commit too, not one per fix.

WHAT IT COUNTS. The commits on main newer than the newest one the server marked
`vm/deploy` success, plus the commits this push adds. One GraphQL call reads
the last 100 commits of main with their status contexts. The repository is
`repo` in `.claude/project.json`, else the `origin` remote.

THE WAY THROUGH. A push whose commits carry the trailer `Unblocks-deploy: yes`
goes through whatever the queue: the commit that fixes a frozen deploy must
never be refused by the jam it fixes. `git push --no-verify` is the human's
waiver, as for every hook here.

FAILURE POLICY: fail open on everything it cannot do. No gh, no network, no
repository name, no `vm/deploy` mark in the last 100 commits, a push that is
not to main -> the push goes, with one line on stderr when there is something
worth saying. Only a count that was read and is over the limit refuses (exit 1).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

LIMIT = int(os.environ.get("PUSH_QUEUE_LIMIT", "15"))
_ZERO = "0" * 40
_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: "refs/heads/main") {
      target { ... on Commit { history(first: 100) { nodes {
        oid status { contexts { context state } }
      } } } }
    }
  }
}
"""


def undeployed(history: list[dict]) -> int | None:
    """How many commits, newest first, come before the newest one marked
    deployed; None when none of them carries the mark."""
    for count, node in enumerate(history):
        contexts = ((node.get("status") or {}).get("contexts")) or []
        if any(c.get("context") == "vm/deploy" and c.get("state") == "SUCCESS" for c in contexts):
            return count
    return None


def verdict(queue: int, pushed: int, unblocks: bool, limit: int = LIMIT) -> str | None:
    """The refusal to print, or None when the push may go."""
    if unblocks or queue + pushed <= limit:
        return None
    return (
        f"BLOCKED: the deploy queue would hold {queue + pushed} commits "
        f"({queue} already waiting, {pushed} in this push; the limit is {limit}).\n"
        "The VM deploys one commit per run, so many small commits clog it.\n"
        "Combine this work into one commit (git reset --soft origin/main, then "
        "commit once) and push again. A commit that fixes a frozen deploy may\n"
        "carry the trailer 'Unblocks-deploy: yes' to go through."
    )


def _repo() -> str | None:
    """``owner/name`` from .claude/project.json, else from the origin remote, else None."""
    try:
        top = _git("rev-parse", "--show-toplevel").strip()
        named = json.loads((pathlib.Path(top) / ".claude" / "project.json").read_text()).get("repo") or ""
        if "/" in named:
            return named
        url = _git("remote", "get-url", "origin").strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    found = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    return f"{found.group(1)}/{found.group(2)}" if found else None


def _history() -> list[dict] | None:
    repo = _repo()
    if not repo:
        return None
    owner, name = repo.split("/", 1)
    try:
        out = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return json.loads(out)["data"]["repository"]["ref"]["target"]["history"]["nodes"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _pushed(local: str, remote: str) -> tuple[int, bool] | None:
    """How many commits the push adds to main, and whether one says it
    unblocks the deploy."""
    try:
        span = local if remote == _ZERO else f"{remote}..{local}"
        bodies = _git("log", "--format=%B%x00", span)
    except (OSError, subprocess.SubprocessError):
        return None
    messages = [body for body in bodies.split("\x00") if body.strip()]
    unblocks = any("unblocks-deploy: yes" in body.lower() for body in messages)
    return len(messages), unblocks


def main(stdin=sys.stdin) -> int:
    for line in stdin:
        parts = line.split()
        if len(parts) != 4 or parts[2] != "refs/heads/main" or parts[1] == _ZERO:
            continue
        pushed = _pushed(parts[1], parts[3])
        if pushed is None:
            continue
        history = _history()
        queue = undeployed(history) if history else None
        if queue is None:
            print("note: could not read the deploy queue; the push goes unchecked", file=sys.stderr)
            continue
        refusal = verdict(queue, pushed[0], pushed[1])
        if refusal:
            print(refusal, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
