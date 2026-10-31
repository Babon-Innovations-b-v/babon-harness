"""The character caps upstream OpenClaw applies to a workspace bootstrap file,
enforced here by refusing rather than by truncating.

Upstream injects each bootstrap file into the system prompt up to
`agents.defaults.bootstrapMaxChars`, 20000 by default, and all of them together
up to `bootstrapTotalMaxChars`, 60000 by default. Past either number it cuts,
silently, from the end.

That is why this refuses instead. SOUL.md renders the seed doctrine first and
everything the team has TAUGHT the assistant after it, so the end of that file is
exactly the part this whole exercise exists to carry, and a silent cut takes
the newest lesson first. A render that will not fit is a decision for a person
(compact the principles table), not a byte count for a truncator to settle.

This module does not own the caps as policy: it owns the numbers upstream
already published, and the choice to fail on them.

Public callables: `check_budget(files)`.

FAILURE POLICY: Tier-1 fail-loud. `WorkspaceTooLong` propagates and the caller
writes nothing, so the gateway keeps the last complete set of files.
"""
from __future__ import annotations

from typing import Protocol, Sequence

#: Upstream's `agents.defaults.bootstrapMaxChars` default, per file.
PER_FILE_MAX_CHARS = 20_000

#: Upstream's `agents.defaults.bootstrapTotalMaxChars` default, across files.
TOTAL_MAX_CHARS = 60_000

#: What the whole set is called when the total, rather than one file, is what
#: overflowed. It is not a filename on purpose: no single file is at fault.
WHOLE_SET = "the workspace as a whole"


class _Sized(Protocol):
    """What `check_budget` needs of a rendered file: a name and its text.

    Structural rather than the concrete `render.WorkspaceFile`, because
    `render` imports this module and the reverse import would be a cycle.
    """

    name: str
    text: str


class WorkspaceTooLong(RuntimeError):
    """A rendered workspace file, or the whole set, is past what upstream will
    inject without cutting it."""

    def __init__(self, name: str, chars: int, cap: int) -> None:
        self.name = name
        self.chars = chars
        self.cap = cap
        super().__init__(
            f"{name} rendered {chars} characters against a cap of {cap}; "
            "upstream would truncate it from the end, which is where the "
            "learned principles are. Compact the principles table instead."
        )


def check_budget(files: Sequence[_Sized]) -> None:
    """Raise `WorkspaceTooLong` when any file, or the set, is over cap.

    Per-file first, so the message names the file a reader has to shorten
    rather than the sum nobody can act on.
    """
    for rendered in files:
        if len(rendered.text) > PER_FILE_MAX_CHARS:
            raise WorkspaceTooLong(rendered.name, len(rendered.text), PER_FILE_MAX_CHARS)
    total = sum(len(rendered.text) for rendered in files)
    if total > TOTAL_MAX_CHARS:
        raise WorkspaceTooLong(WHOLE_SET, total, TOTAL_MAX_CHARS)
