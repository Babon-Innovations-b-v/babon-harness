"""Minutes reach the assistant once with the bearer, and come back as every issue opened or updated.

WHAT IT PINS. `board.send_to_assistant`: one POST to
`<OPENCLAW_NOTIFY_URL>/webhook/notulen` carrying the shared bearer and the
meeting, answered by the issues the assistant opened plus the ones it updated;
a request that never arrived is `AssistantUnreachable` (so the caller may
release its claim), and a missing setting is a KeyError naming it. The HTTP
session is a recorder that answers what the case scripts.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The URL,
header and body are written out by hand from the made-up settings and meeting,
and the returned numbers are the scripted `issues` followed by `updated`.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops the
updated issues from the answer, so the opened-and-updated case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from apps.notulen.app.core.board import AssistantUnreachable, send_to_assistant

# The library's own ConnectionError, taken from the module that catches it, so
# the test imports no HTTP client of its own.
send_module = importlib.import_module("apps.notulen.app.core.board.send_to_assistant")

SETTINGS = {"OPENCLAW_WEBHOOK_SECRET": "made-up-bearer", "OPENCLAW_NOTIFY_URL": "http://assistant.internal:8080/"}
SENT = (
    "http://assistant.internal:8080/webhook/notulen",
    {"Authorization": "Bearer made-up-bearer"},
    {"job_id": "job-7", "title": "Weekly", "meeting_date": "2026-05-04",
     "markdown": "## Action items", "minutes_url": "https://example.org/m"},
)

CASES = [
    pytest.param(SETTINGS, {"issues": [41, 42], "updated": [7]}, ([41, 42, 7], [SENT]), id="opened-and-updated"),
    pytest.param(SETTINGS, {"issues": [], "updated": None}, ([], [SENT]), id="a-meeting-that-leaves-the-board-alone"),
    pytest.param(SETTINGS, "unreachable", ("AssistantUnreachable", [SENT]), id="never-arrived"),
    pytest.param({**SETTINGS, "OPENCLAW_WEBHOOK_SECRET": ""}, {}, ("KeyError", []), id="no-bearer-sends-nothing"),
]


class _Session:
    def __init__(self, answer) -> None:
        self.answer, self.sent = answer, []

    def post(self, url: str, *, headers: dict, json: dict, timeout: int) -> SimpleNamespace:
        self.sent.append((url, headers, json))
        if self.answer == "unreachable":
            raise send_module.requests.ConnectionError("connection refused")
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.answer)


@pytest.mark.parametrize("settings, answer, expected", CASES)
def test_minutes_reach_the_assistant_once_with_the_bearer_and_come_back_as_every_issue_opened_or_updated(
        settings: dict, answer, expected: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """(issues returned or the refusal, requests sent) is the hand-written pair."""
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    session = _Session(answer)
    try:
        outcome: object = send_to_assistant(
            "job-7", "Weekly", "2026-05-04", "## Action items", "https://example.org/m", session=session,
        )
    except (AssistantUnreachable, KeyError) as refusal:
        outcome = type(refusal).__name__
    assert (outcome, session.sent) == expected
