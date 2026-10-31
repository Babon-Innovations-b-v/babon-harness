"""IDENTITY.md: what the assistant is, and what it may do.

Upstream OpenClaw ships this file as a fill-in-the-blanks stub and tells the
agent to write it during its first conversation, which is how an assistant with
no employer ends up choosing its own name. The assistant already has one, and a job
description that was decided by people, so the file is rendered rather than
discovered.

The labels are upstream's: it parses `- **Label:** value` lines, and its own
stub says Theme, Creature and Vibe all feed one effective identity value,
preferred in that order, while only Name, Theme, Emoji and Avatar are ever
written back into the file by `openclaw agents set-identity`. The labels
written here are Name, Creature and Vibe. The theme is NOT written here: it is
set in `gateway_config_patch.json` as `agents.entries.main.identity.theme`,
which is the value the gateway actually carries. The Vibe line below says the
same thing in the same words for the reader of this file; change one and change
the other. Emoji and Avatar are left out because nothing in this company signs a
message with a picture, and the voice block already says to sign nothing.

The "may do" half is not decoration. Seed principle 1 says the assistant advises and
does not operate, and the mechanism behind it is no longer "the
tools only look": it is the decision per tool in `core/tools/gateway_surface.py`
about what the MCP door serves, plus the requester the door makes
every write name and records it under. Stating the boundary here means the
sentence and the mechanism agree.

Public callables: `render_identity()`.

FAILURE POLICY: constants only, nothing to fail.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

_IDENTITY = f"""# IDENTITY.md

Rendered from the repository every deploy; an edit here does not survive.

- **Name:** {ASSISTANT_NAME}
- **Vibe:** calm, plain spoken, with a stake in whether the systems stay up.
  Relieved when a scare turns out fine, uneasy when something has been quiet
  too long, never alarmed for effect.
"""


def render_identity() -> str:
    """The rendered IDENTITY.md."""
    return _IDENTITY
