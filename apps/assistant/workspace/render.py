"""The seam: the four workspace bootstrap files, rendered together or not at
all.

One callable so there is one answer to "what does the gateway read". The four
renderers are separate modules because they carry separate judgment; the set is
one thing because upstream injects it as one prompt and caps it as one prompt,
and because a caller writing three of four files leaves the gateway holding a
mixture of today's doctrine and last week's reader profiles.

The budget check runs here, after all four have rendered and before any
caller has anything to write, for the same reason.

Public callables: `render_workspace()`. `WorkspaceFile` rides with it.

FAILURE POLICY: Tier-1 fail-loud. Anything that fails, including the budget,
raises and the caller gets nothing, so the gateway keeps the last complete set.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.assistant.workspace import agents as _agents
from apps.assistant.workspace import budget as _budget
from apps.assistant.workspace import identity as _identity
from apps.assistant.workspace import soul as _soul
from apps.assistant.workspace import user as _user


@dataclass(frozen=True)
class WorkspaceFile:
    """One rendered bootstrap file. `name` is upstream's filename, which is
    also its enum value in `agents.defaults.skipOptionalBootstrapFiles`, so it
    is never ours to invent."""

    name: str
    text: str


def render_workspace() -> tuple[WorkspaceFile, ...]:
    """Every workspace bootstrap file the project owns, in the order upstream lists
    them, checked against upstream's character caps."""
    files = (
        WorkspaceFile(name="AGENTS.md", text=_agents.render_agents()),
        WorkspaceFile(name="SOUL.md", text=_soul.render_soul()),
        WorkspaceFile(name="USER.md", text=_user.render_user()),
        WorkspaceFile(name="IDENTITY.md", text=_identity.render_identity()),
    )
    _budget.check_budget(files)
    return files
