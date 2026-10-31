"""Terminal tool: `submit_triage_decision`.

The LLM signals "I'm done investigating, here's my decision" by
calling this tool. The triage loop watches for it and short-circuits
the iteration loop.

Returning a literal "submitted" string from the executor is a
convention: when the loop sees the tool was called, it pulls the
decision payload from the tool_input and exits the loop. The
returned string never gets fed back to the LLM (the conversation
ends here). Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: pure constant return, nothing to fail.
"""
from __future__ import annotations

from typing import Any

NAME = "submit_triage_decision"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Submit your final triage decision. Call this exactly once "
        "when you've finished investigating. The Signal draft must be "
        "<=280 chars, written in the caveman style (terse fragments, "
        "no filler). Set `signal_draft` to null when decision='silent'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["silent", "enrich", "page-raw"],
            },
            "reason": {
                "type": "string",
                "description": "Short fragment, why you picked this decision.",
            },
            "signal_draft": {
                "type": ["string", "null"],
                "description": "Signal message draft, <=280 chars. null if decision='silent'.",
            },
            "covered_by_fingerprint": {
                "type": ["string", "null"],
                "description": (
                    "Only when silencing because ANOTHER alert's page already "
                    "covers this one: that alert's fingerprint. Code checks it "
                    "was delivered; a silence that claims a page nobody "
                    "received is turned into a page."
                ),
            },
            "worklist_item": {
                "type": ["integer", "null"],
                "description": (
                    "Only when this page is about a problem an open worklist "
                    "item already tracks: that item's id, so the reply to the "
                    "page can be recorded against it. null otherwise; never guess."
                ),
            },
        },
        "required": ["decision", "reason", "signal_draft"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    return "submitted"
