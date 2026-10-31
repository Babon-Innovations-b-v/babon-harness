"""The morning brief's ask fixes the quiet-day line and forbids calling anything fine.

WHAT IT PINS. The `harness:morning-brief` ask in `gateway_automations.json`.
A quiet day left as "one line" of the model's choosing invites a status claim
such as "your calendar is clear" over a calendar holding an event, or a line
listing recoveries. A clause telling it to leave out anything already said
drops items still waiting on the reader.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The phrases are
the brief's written contract: one exact quiet-day sentence, a ban on calling
anything clear or fine, the worklist and an unbooked call link named as things
to check, and no "already told" clause. This pins the ask as text; whether the
model follows it is checked by the next transcript sweep, not here.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

import json
from pathlib import Path



def _brief() -> str:
    automations = fragment.render_automations()["automations"]
    return next(job["message"] for job in automations if job["declarationKey"] == "harness:morning-brief")


def test_the_morning_brief_never_calls_a_quiet_day_fine() -> None:
    """One fixed quiet-day line, no status claims, no 'already told' drop."""
    brief = _brief()
    assert "send exactly 'Nothing needs you today.'" in brief
    assert "Never call anything clear, fine, back or steady" in brief
    assert "your worklist" in brief
    assert "A worklist item for them goes in unless they were told it before" in brief
    assert "call link" in brief
    assert "anything you already told" not in brief
