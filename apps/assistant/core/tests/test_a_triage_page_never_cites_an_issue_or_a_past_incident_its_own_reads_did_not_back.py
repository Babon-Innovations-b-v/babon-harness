"""A triage page never cites an issue or a past incident its own reads did not
back.

WHAT IT PINS. `core.triage.triage` and `core.claims.unread_issue_numbers`,
across their public interfaces, with the model and the tools stubbed. An issue
spelled out as "issue 42" counts as a citation; a page citing one no reading
of the pass carried, or diagnosing by analogy to a past incident ("Same pattern
as the earlier incidents") that the reads do not show, is nudged once and then
loses those sentences. A reading that does carry the issue keeps it.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The one reading
is a kubectl events text written here, with no issue number and
no word of the analogy in it; the control reading is gh_issue_view output
carrying "number: 42". Which sentence is backed is read off those by eye.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

_EVENTS = (
    "18:03 Normal NodeNotSchedulable node/batch-gpu-old drained\n"
    "18:14 Normal NodeReady node/batch-gpu-new status is now: NodeReady\n"
)
_ISSUE_PAGE = (
    "Notulen job for the weekly sync failed: DeadlineExceeded. "
    "Same GPU driver-upgrade timing issue as last month (issue 42)."
)
_ANALOGY_PAGE = (
    "Notulen job for the weekly sync stuck 30+ min waiting for a GPU. "
    "Same pattern as the earlier incidents."
)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools
    from apps.assistant.core.triage import Alert, triage

    world = {"reading": _EVENTS, "draft": _ISSUE_PAGE}
    shown: list = []
    monkeypatch.setattr(tools, "execute", lambda name, tool_input: world["reading"])

    def fake_run(*, messages, dispatch, **_ignored):
        shown.append(messages[-1]["content"])
        if len(shown) == 1:
            dispatch("kubectl_events", {"namespace": "notulen"})
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(shown)}", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "job failed", "signal_draft": world["draft"]},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run():
        return triage(
            Alert(
                fingerprint="5d1e0c7f2a9b3e41", status="firing",
                labels={"alertname": "PipelineBroken", "severity": "warning"},
                annotations={"summary": "notulen GPU job failed: DeadlineExceeded"},
                starts_at="2026-10-19T18:25:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, world=world, shown=shown)


def test_a_spelled_out_issue_is_a_citation() -> None:
    from apps.assistant.core import claims

    assert claims.unread_issue_numbers("Same timing issue (issue 42).", set()) == [42]


def test_an_issue_no_reading_carried_is_asked_about_then_left_out(pod) -> None:
    result = pod.run()
    assert "42" in str(pod.shown[1])
    assert "42" not in (result.signal_draft or "")
    assert "DeadlineExceeded" in (result.signal_draft or "")


def test_an_issue_a_reading_carried_stays(pod) -> None:
    pod.world["reading"] = "title:\tGPU driver upgrade timing\nnumber:\t42\n" + _EVENTS
    result = pod.run()
    assert "issue 42" in (result.signal_draft or "")


def test_a_diagnosis_by_analogy_to_a_past_incident_is_left_out(pod) -> None:
    pod.world["draft"] = _ANALOGY_PAGE
    result = pod.run()
    assert "Same pattern" not in (result.signal_draft or "")
    assert "stuck 30+ min" in (result.signal_draft or "")
