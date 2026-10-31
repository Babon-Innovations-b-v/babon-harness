"""Whether a set of issues is open or closed, in one GitHub call.

Not a tool: no `NAME`, never in the registry. `core/closed_card_mutes.py`
asks it which of the cards the assistant filed have been closed, so the morning brief
can say a mute is still standing on a closed card.

ONE CALL, CACHED. The cards are a few dozen numbers, and a `gh issue view`
each would be a few dozen subprocesses on every `my_actions` read. So it is a
single GraphQL query with one alias per number, through the same read-only
`gh` and `GH_TOKEN` the gh tools use, and each answer is kept for
`_CACHE_SECONDS`, because a card closing is not news that has to land inside
the minute.

FAILURE POLICY: Tier-1. A failed call raises `RuntimeError` with gh's words,
and the caller says the states could not be read: an unread state must never
read as open.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_OWNER, GITHUB_NAME

import json
import subprocess
import time
from collections.abc import Iterable

_OWNER, _NAME = GITHUB_OWNER, GITHUB_NAME
_TIMEOUT_SECONDS = 20
_CACHE_SECONDS = 15 * 60

#: number -> (state, monotonic time it was read). States are GitHub's: OPEN or
#: CLOSED. A number GitHub does not know is left out of the answer.
_cache: dict[int, tuple[str, float]] = {}


def states(numbers: Iterable[int]) -> dict[int, str]:
    """`OPEN` or `CLOSED` for each issue number GitHub knows, from the cache
    where it is fresh and one GraphQL call for the rest."""
    wanted = sorted({int(number) for number in numbers})
    now = time.monotonic()
    stale = [number for number in wanted if now - _cache.get(number, ("", -1e18))[1] > _CACHE_SECONDS]
    if stale:
        for number, state in _read(stale).items():
            _cache[number] = (state, now)
    return {number: _cache[number][0] for number in wanted if number in _cache}


def _read(numbers: list[int]) -> dict[int, str]:
    """One GraphQL query for `numbers`. Raises RuntimeError when nothing came back."""
    aliases = " ".join(f"i{number}:issue(number:{number}){{state}}" for number in numbers)
    query = f'query{{repository(owner:"{_OWNER}",name:"{_NAME}"){{{aliases}}}}}'
    done = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False,
    )
    # A number that is not an issue makes gh exit non-zero while the data for
    # every other alias is still there, so the exit code alone is not the answer.
    try:
        repository = (json.loads(done.stdout or "{}").get("data") or {}).get("repository") or {}
    except ValueError:
        repository = {}
    if not repository:
        raise RuntimeError(
            f"gh graphql failed (rc={done.returncode}): {done.stderr.strip()[:200]}"
        )
    return {
        int(alias[1:]): str(node["state"])
        for alias, node in repository.items()
        if node and node.get("state")
    }
