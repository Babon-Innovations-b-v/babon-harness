"""A push to main waits while the deploy queue is long, and a commit that unblocks the deploy goes.

WHAT IT PINS. `.claude/hooks/local/push_queue.py`, which `.claude/hooks/local/pre-push`
runs before every push: `undeployed` counts the commits on main before the
newest one marked `vm/deploy` success, and `verdict` refuses when that count
plus the pushed commits passes the limit.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The history is
written by hand: two unmarked commits, then a deployed one, so the queue is 2;
with a limit of 15, ten waiting plus five pushed is 15 and goes, plus six is 16
and is refused, and the trailer lets even 41 through.

WHAT IT WAS PROVED AGAINST. The register row's break makes `verdict` ignore the
limit, so the 16-commit push goes through.

GUARDS. The 2026-11-02 deploy jam: one session pushed 62 commits in an hour.
"""
from __future__ import annotations

import importlib.util
import pathlib

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "local" / "push_queue.py"


def _push_queue():
    spec = importlib.util.spec_from_file_location("push_queue", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _commit(deployed: bool) -> dict:
    contexts = [{"context": "vm/deploy", "state": "SUCCESS"}] if deployed else []
    return {"oid": "x", "status": {"contexts": contexts}}


def test_a_push_waits_while_the_deploy_queue_is_long_and_an_unblocking_commit_goes() -> None:
    """The queue is counted to the newest deployed commit; past the limit refuses, the trailer passes."""
    queue = _push_queue()
    assert queue.undeployed([_commit(False), _commit(False), _commit(True), _commit(False)]) == 2
    assert queue.undeployed([_commit(False)]) is None
    assert queue.verdict(10, 5, False, limit=15) is None
    assert "BLOCKED" in queue.verdict(10, 6, False, limit=15)
    assert queue.verdict(40, 1, True, limit=15) is None
