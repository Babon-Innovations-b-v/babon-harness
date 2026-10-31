"""Every scheduled report tells the model that nobody asked, so its writes are booked to the assistant.

WHAT IT PINS. `gateway_automations.json`, the asks the gateway's cron runs are
given, against the two seams that read who a send was booked to: the door's
`_SELF_PROVENANCE_TOOLS`, which must accept `message_teammate` under the assistant's
name, and `sent_feed.RELAYED_LOOPS`, which relays a send booked to the assistant
(`teammate-self`) into the chat session as a message nobody asked for.
A brief that says only "send the owner the result" reads to the model as the
owner having asked, so the send is booked `teammate-asked`, logged "asked by the
owner" and never reaches the chat session a reply lands in.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The sentence is
read out of the JSON file the gateway is configured from, and the door rule it
must agree with is the one `workspace/capabilities.py` states: when nobody
asked, `requested_by` is 'the assistant'.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

from apps.assistant.shared.name import ASSISTANT_NAME

import json
from pathlib import Path

from apps.assistant.core import sent_feed
from apps.assistant.core.tools import write_tools
from apps.assistant.gates import mcp

_BOOKED_TO_ASSISTANT = f'requested_by "{ASSISTANT_NAME}"'


def test_every_scheduled_report_books_its_writes_to_assistant() -> None:
    """Each cron ask that sends a message says the run books to the assistant, and the relay carries it."""
    automations = fragment.render_automations()["automations"]
    senders = [job for job in automations if "message_teammate" in job["message"]]
    assert senders, "no scheduled report sends through message_teammate any more"
    for job in senders:
        assert "Nobody asked for this run" in job["message"], job["declarationKey"]
        assert _BOOKED_TO_ASSISTANT in job["message"], job["declarationKey"]

    assert write_tools.MESSAGE_TEAMMATE in mcp._SELF_PROVENANCE_TOOLS
    assert "teammate-self" in sent_feed.RELAYED_LOOPS
