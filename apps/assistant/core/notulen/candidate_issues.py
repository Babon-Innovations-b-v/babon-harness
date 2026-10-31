"""The open board, as the choices the assistant is allowed to make.

Everything a meeting can land on has to exist, so this reads the live board
rather than the packed index. The index in the assistant's image carries issue rows
too, but they come from a cache refreshed by hand, and a stale parent is the
one mistake that is expensive here: nesting a real action point under a
closed or renamed epic puts it somewhere nobody looks.

What comes back is the enum `decide_placements` closes its tool schema over.
The model can pick a number from this list or it can ask for a new root; it
cannot type a number of its own, so a hallucinated parent is not a failure
mode this path has.

Read with the read-only `gh`, like `issue_sweep` does. Writes are a separate
question and go through `github_act`.

FAILURE POLICY: Tier-2, a listing that fails returns an empty list and the
caller reports that it could not read the board, rather than filing a
meeting into nothing.
"""
from __future__ import annotations

from apps.assistant.shared.project import AREA_LABEL_PREFIX, GITHUB_REPO

import json
import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger("openclaw.notulen")

_REPO = GITHUB_REPO
_PRD_LABEL = "PRD"
_AREA_PREFIX = AREA_LABEL_PREFIX
_TIMEOUT_S = 30
#: GitHub's GraphQL connections refuse anything over 100 per page, with an
#: error rather than a truncated answer. Asking for more in one go fails the
#: listing, and the caller then correctly refuses to guess at parents with no
#: board to read, so nothing is filed.
_PAGE = 100
#: The board is a forest of a few dozen roots with children under them; this
#: is a ceiling against a runaway page, not a real limit.
_LIMIT = 300


@dataclass(frozen=True)
class Candidate:
    """One open issue a meeting could land on or under."""

    number: int
    title: str
    area: str
    is_root: bool
    #: A root with no parent is where new work may nest. A child cannot take
    #: children of its own without making a fourth layer the board does not
    #: show, so only roots are offered as parents.
    has_parent: bool

    def as_line(self) -> str:
        """One line for the model's prompt: what it is and where it sits."""
        kind = "root PRD" if self.is_root else "issue"
        return f"#{self.number} [{kind}, {self.area or 'no department'}] {self.title}"


_QUERY = """
query($owner:String!,$name:String!,$page:Int!,$after:String){
  repository(owner:$owner,name:$name){
    issues(states:OPEN,first:$page,after:$after,
           orderBy:{field:CREATED_AT,direction:DESC}){
      pageInfo{ hasNextPage endCursor }
      nodes{ number title parent{number} labels(first:20){nodes{name}} }
    }
  }
}
"""


def candidate_issues() -> list[Candidate]:
    """Every open issue, newest first, with enough to choose a parent by."""
    owner, name = _REPO.split("/")
    nodes: list[dict] = []
    cursor: str | None = None
    try:
        while len(nodes) < _LIMIT:
            args = ["gh", "api", "graphql", "-f", f"query={_QUERY}",
                    "-F", f"owner={owner}", "-F", f"name={name}",
                    "-F", f"page={_PAGE}"]
            if cursor:
                args += ["-F", f"after={cursor}"]
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=_TIMEOUT_S, check=False,
            )
            if result.returncode != 0:
                log.warning("could not list the board: %s", result.stderr.strip()[:200])
                return []
            page = json.loads(result.stdout)["data"]["repository"]["issues"]
            nodes.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
    except Exception as exc:  # noqa: BLE001, Tier-2: an unreadable board is reported, not raised
        log.warning("could not read the board: %s", exc)
        return []

    candidates: list[Candidate] = []
    for node in nodes:
        labels = [label["name"] for label in (node.get("labels") or {}).get("nodes", [])]
        area = next(
            (label[len(_AREA_PREFIX):] for label in labels
             if label.startswith(_AREA_PREFIX)),
            "",
        )
        candidates.append(Candidate(
            number=int(node["number"]),
            title=node["title"],
            area=area,
            is_root=_PRD_LABEL in labels and not node.get("parent"),
            has_parent=bool(node.get("parent")),
        ))
    return candidates
