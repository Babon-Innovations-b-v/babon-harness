"""A triage pass stores what it read beside what it said, and a critical
silence on an unread stamp pages.

WHAT IT PINS. `core.triage.triage` across its public interface, with the tools
and the model stubbed and the readings read back through
`state.message_evidence.said_between`. A pass that ran the model leaves one
row on the loop `triage`, keyed by the alert's fingerprint, holding its
readings and its draft or its reason for silence. A silence on a critical whose
reason carries a date, time or number that no reading of the pass contains
becomes a raw page.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The one tool
call returns a fixed text the test wrote, so whether "6f6f6f6f" or "13:55" is
in any reading is read off that text and the alert payload by eye: in the
first case neither is, in the second the reading carries both.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

_FINGERPRINT = "f3fe41d09b35fe4b"
_REASON = "Alex fixed it in commit 6f6f6f6f at 13:55 UTC, 48s after the alert fired."


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh table, one tool that returns `reading`, and a model that reads
    once and then silences with `_REASON`."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    world = {"reading": "HTTP/2 200"}
    monkeypatch.setattr(tools, "execute", lambda name, tool_input: world["reading"])

    def fake_run(*, dispatch, **_ignored):
        dispatch("run_shell", {"command": "curl -sI https://app.example.org"})
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "silent", "reason": _REASON, "signal_draft": None},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run():
        started = datetime.now(timezone.utc)
        if started.strftime("%H:%M") == "13:55":
            # The reason's clock time must not reach the payload by coincidence.
            started -= timedelta(minutes=2)
        return triage(
            Alert(
                fingerprint=_FINGERPRINT, status="firing",
                labels={"alertname": "ContainerRestartingExcessively", "severity": "critical"},
                annotations={"summary": "web-dashboard restarted more than 10 times in 1h"},
                starts_at=started.isoformat(),
                ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, world=world, state=state)


def test_the_pass_leaves_its_readings_and_its_reason_on_the_loop_triage(pod) -> None:
    pod.run()
    rows = [
        row for row in pod.state.message_evidence.said_between("0000", "9999")
        if row["loop"] == "triage"
    ]
    assert len(rows) == 1
    assert rows[0]["recipient"] == _FINGERPRINT
    assert any("HTTP/2 200" in reading["excerpt"] for reading in rows[0]["readings"])


def test_a_critical_silenced_on_a_stamp_nothing_read_pages(pod) -> None:
    assert pod.run().decision == "page-raw"


def test_a_critical_silenced_on_a_stamp_a_reading_carries_stays_silent(pod) -> None:
    pod.world["reading"] = "6f6f6f6f 2026-10-20T13:55:07Z web: pin APP_VERSION (48s)"
    assert pod.run().decision == "silent"
