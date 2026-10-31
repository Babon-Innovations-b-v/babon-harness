"""the assistant's judgment, rendered as the workspace files upstream OpenClaw reads
(piece 2).

Upstream OpenClaw builds its system prompt from three optional bootstrap files
in an agent's workspace directory: `SOUL.md` (how it thinks and how it writes),
`USER.md` (who it is talking to and how each of them reads) and `IDENTITY.md`
(what it is). The names, and the caps, are upstream's own: they are the enum of
`agents.defaults.skipOptionalBootstrapFiles` in the gateway's config schema,
each file is injected up to `bootstrapMaxChars` (20000 by default) and all of
them together up to `bootstrapTotalMaxChars` (60000 by default). Checked
against the gateway's config schema.

This package renders those three files from the LIVE modules, never from a hand
copy. A principle the owner teaches over Signal lands in the `principles` state
table, `core.principles.render` picks it up for every pod loop, and the same
call renders it into SOUL.md here. There is one doctrine, and it has one home.

Tier declaration: Tier S, flat leaf, five implementation files.

Module map:
    render.py    the seam: `render_workspace()` plus the `WorkspaceFile` pair
    soul.py      SOUL.md: the principles block, the voice block, and a
                 capability paragraph written for the gateway
    user.py      USER.md: one directive block per teammate in the registry
    identity.py  IDENTITY.md: the constant `- **Label:** value` lines
    budget.py    `check_budget`: refuse an over-cap render rather than let
                 upstream truncate it

WHAT GOES WHERE, decided per module rather than per file. Three buckets.

PROSE, rendered here: `core.principles` and `core.voice` are pure prompt text
with nothing enforcing them, which is exactly what a bootstrap file is; and
`core.people`'s style tables plus the `person_rules` table are the same thing
about a reader instead of about the writer.

CONFIG, in `gateway_config_patch.json`: the workspace path, the bootstrap file
list and the agent's name and theme. Anything the gateway already has a key for
belongs in its key, not in a sentence asking it to behave that way.

CODE, staying in this repository: quiet hours is the sharp one and it stays.
`core.quiet_hours.quiet_now` gates the wire inside `core.page_hold.release`,
and `core.quiet_hours.ends_at_minute` hands `page_hold` the minute of local
midnight at which the morning starts, deliberately from one clock. No
sentence in a prompt returns a minute, and the gateway config has no key that
could: a sweep of the whole schema for quiet, dnd, snooze, mute and window
found one time window, `agents.entries.<id>.heartbeat.activeHours`, which
bounds when the agent wakes ITSELF and says nothing about the wire. So an
unsolicited send stays behind `page_hold.release` in this repository's code,
and SOUL.md carries no sentence claiming otherwise. The same verdict, for the
same reason, covers the claim guards in `core.claims`, the send seam in
`core.signal_text`, the delivery ledger in `core.outbound`, the two paging
floors, and `core.people.identify`'s strong-versus-weak identity rule.

Public callables: `render_workspace()`.

FAILURE POLICY: Tier-1 fail-loud. This renders a prompt, and a half-rendered
prompt is the assistant that has quietly forgotten what it was taught, which nothing
downstream can see. A read that fails raises, `check_budget` raises rather than
truncating, and the caller writes nothing. The deploy step that carries the
files to the VM is the Tier-2 half: it leaves yesterday's files in place.
"""
from __future__ import annotations

from apps.assistant.workspace.budget import WorkspaceTooLong
from apps.assistant.workspace.render import WorkspaceFile, render_workspace
from apps.assistant.workspace.user import EmptyRegistry

__all__ = ["EmptyRegistry", "WorkspaceFile", "WorkspaceTooLong", "render_workspace"]
