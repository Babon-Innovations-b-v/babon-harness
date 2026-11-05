"""Minutes the notulen app sends reach the assistant's route and come back as the issues it filed.

WHAT IT PINS. How the two apps fit: `apps/notulen`'s `send_to_assistant` posts
a meeting, and `apps/assistant`'s gate answers it at `/webhook/notulen`. The two
sides agree on the bearer, the body's field names and the answer's
`issues` and `updated` keys only by convention, so a rename on one side reads
on the other as a meeting that put nothing on the board. The notulen side's
HTTP session is pointed at the assistant's app through FastAPI's test client;
only the board work behind the route (`file_minutes`) and the Signal send are
replaced.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The filed
result is made up here (opened 41 and 42, updated 7), so the numbers the sender
must get back are those, in that order; a wrong bearer must be refused before
any filing, and a meeting with no text is refused by the route as incomplete.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row renames
`markdown` in the body the notulen app sends, so every case that should file
is refused as missing it.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest

from apps.notulen.app.core.board import send_to_assistant

send_module = importlib.import_module("apps.notulen.app.core.board.send_to_assistant")
BEARER = "made-up-shared-bearer"

CASES = [
    pytest.param(BEARER, "## Action items\n| Plan | Sam | Friday |", ([41, 42, 7], 1), id="filed-and-reported-back"),
    pytest.param("guessed", "## Action items", ("HTTP 401", 0), id="a-wrong-bearer-files-nothing"),
    pytest.param(BEARER, "", ("HTTP 400", 0), id="a-meeting-with-no-text-is-refused"),
]


class _Through:
    """A requests-shaped session whose post lands on the assistant's own app.

    Both apps read one variable name for the shared bearer and share this
    process, so the assistant's own secret is put in place while the request
    is being answered and the sender's is put back afterwards.
    """

    def __init__(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        self.client, self.monkeypatch = client, monkeypatch

    def post(self, url: str, *, headers: dict, json: dict, timeout: int):
        sender_secret = os.environ["OPENCLAW_WEBHOOK_SECRET"]
        self.monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", BEARER)
        response = self.client.post(url.split("8080", 1)[1], headers=headers, json=json)
        self.monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", sender_secret)

        def raise_for_status() -> None:
            if response.status_code >= 400:
                raise send_module.requests.HTTPError(f"HTTP {response.status_code}")

        return SimpleNamespace(raise_for_status=raise_for_status, json=response.json)


@pytest.mark.parametrize("sent_bearer, markdown, expected", CASES)
def test_minutes_the_notulen_app_sends_reach_the_assistants_route_and_come_back_as_the_issues_it_filed(
        sent_bearer: str, markdown: str, expected: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """(issues the sender got back or the refusal, meetings filed) is the made-up answer."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    from fastapi.testclient import TestClient

    from apps.assistant.core import state
    from apps.assistant.gates import app as gate_app

    state.reset_for_tests()
    filed: list[tuple] = []
    result = SimpleNamespace(issues=[41, 42], root=None, updated=[7], comments=[], problems=[],
                             as_report=lambda title: f"Minutes of {title} filed.")
    monkeypatch.setattr(gate_app.openclaw_notulen, "file_minutes", lambda *args: filed.append(args) or result)
    monkeypatch.setattr(gate_app, "_send_beat", lambda body: True)
    session = _Through(TestClient(gate_app.app), monkeypatch)
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", sent_bearer)
    monkeypatch.setenv("OPENCLAW_NOTIFY_URL", "http://assistant.internal:8080")
    try:
        outcome: object = send_to_assistant("job-7", "Weekly", "2026-05-04", markdown, "", session=session)
    except send_module.requests.HTTPError as refusal:
        outcome = str(refusal)
    assert (outcome, len(filed)) == expected
