"""A silence that names its cover only in prose is asked once for it before it
becomes a raw page.

WHAT IT PINS. `core.triage.triage` and `core.page_hold.release`, across their
public interfaces, with the tables seeded through `state.record_alert` and
`state.hold_page`. A silence that claims an earlier page without naming a
delivered one is answered once with the pages that went out or are queued since
the alert began, and stands if the model then names one. With nothing to name it
pages at once. A queued cover takes the silenced fingerprint along when it is
released. A raw page does not stop the checked page written after it. A silence
whose own page is still queued stands, and a page written in answer to the cover
question gets the same draft checks as a first draft.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture is
two alerts: a1b2c3d4e5f60718 delivered, 0f1e2d3c4b5a6978 only ever
silent. Whether a page was delivered is read off which rows were recorded with
`signal_sent=True`. The model stub names the cover only if the corrective turn
it is shown contains that fingerprint, which is what a model reading it can do.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

_COVER = "a1b2c3d4e5f60718"
_SILENCED = "0f1e2d3c4b5a6978"
_PROSE = (
    "The tls-watchdog targets-down event was already paged to Alex earlier "
    "today; covered by the earlier page."
)
_NOON = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh table and a model stub whose answers the test scripts."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    turns: list[str] = []
    script: dict = {"reason": _PROSE, "cover_if_shown": None}

    def fake_run(*, messages, **_ignored):
        last = messages[-1]["content"]
        shown = last if isinstance(last, str) else last[0]["content"]
        turns.append(shown)
        cover = script["cover_if_shown"]
        named = cover if cover and len(turns) > 1 and cover in shown else None
        answer = {
            "decision": "silent", "reason": script["reason"], "signal_draft": None,
            "covered_by_fingerprint": script.get("cover_first") or named,
        }
        if len(turns) > 1 and script.get("page_on_retry"):
            answer = {"decision": "enrich", "reason": "paging instead",
                      "signal_draft": script["page_on_retry"]}
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(turns)}", name=tools.SUBMIT_NAME,
            input=answer,
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)

    def run():
        return triage(
            Alert(
                fingerprint=_SILENCED, status="firing",
                labels={"alertname": "TargetDown", "severity": "warning"},
                annotations={"summary": "Prometheus target tls-watchdog down 15m"},
                starts_at="2026-01-01T00:00:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    for _ in range(2):
        state.record_alert(
            fingerprint=_SILENCED, name="TargetDown", severity="warning",
            status="firing", decision="silent", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
    return SimpleNamespace(
        run=run, turns=turns, script=script, state=state, page_hold=page_hold
    )


def _deliver_cover(state) -> None:
    state.record_alert(
        fingerprint=_COVER, name="TargetDown", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )


def test_a_cover_described_in_prose_is_asked_for_and_then_stands(pod) -> None:
    _deliver_cover(pod.state)
    pod.script["cover_if_shown"] = _COVER
    result = pod.run()
    assert len(pod.turns) == 2
    assert result.decision == "silent"
    assert f"covered by the page on {_COVER}" in result.reason


def test_with_nothing_delivered_or_queued_it_pages_without_asking(pod) -> None:
    result = pod.run()
    assert result.decision == "page-raw"
    assert len(pod.turns) == 1


def test_a_silence_saying_the_condition_resolved_is_not_a_page_claim(pod) -> None:
    pod.script["reason"] = "already silenced; the condition has resolved (source_up=1)"
    result = pod.run()
    assert result.decision == "silent"
    assert len(pod.turns) == 1


def test_a_queued_cover_takes_the_silenced_fingerprint_along_when_it_leaves(pod) -> None:
    from apps.assistant.core.state.alerts import last_delivered_at

    pod.state.hold_page(
        "tls-watchdog targets dark.", road="alertmanager",
        subject="TargetDown", severity="warning", key=_COVER,
    )
    pod.script["reason"] = f"covered by the queued page on {_COVER}"
    pod.script["cover_first"] = _COVER
    result = pod.run()
    assert result.decision == "silent"
    assert "queued page" in result.reason
    pod.page_hold.release(now=_NOON)
    assert last_delivered_at(_SILENCED)


def test_a_raw_page_does_not_stop_the_checked_page_written_after_it(pod) -> None:
    landed: list[str] = []
    pod.page_hold._signal_dispatch.send = lambda subject, body: landed.append(body) or True
    for text, minute in (("[RAW] targets dark. I am passing this on unchecked.", 0),
                         ("Prometheus cannot reach the tunnel; the apps are up.", 20)):
        pod.state.hold_page(
            text, road="alertmanager", subject="TargetDown",
            severity="warning", key=_COVER,
        )
        pod.state.record_alert(
            fingerprint=_COVER, name="TargetDown", severity="warning",
            status="firing", decision="enrich", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
        pod.page_hold.release(now=_NOON.replace(minute=minute))
    assert landed[-1].startswith("Prometheus cannot reach the tunnel")


def test_a_resend_whose_own_page_is_queued_stays_silent_and_keeps_that_page(pod) -> None:
    pod.state.hold_page(
        "Prometheus cannot reach the tunnel; the apps are up.", road="alertmanager",
        subject="TargetDown", severity="warning", key=_SILENCED,
    )
    pod.script["reason"] = "Already queued for the morning; same firing."
    result = pod.run()
    assert result.decision == "silent"
    assert "own page queued" in result.reason
    held = pod.state.pending_page_for_key(_SILENCED)
    assert held["text"].startswith("Prometheus cannot reach the tunnel")


def test_a_page_written_in_answer_to_the_cover_question_passes_the_draft_checks(pod) -> None:
    _deliver_cover(pod.state)
    pod.script["page_on_retry"] = (
        "Prometheus target tls-watchdog is down. Need the watchdog restarted."
    )
    result = pod.run()
    assert result.decision == "enrich"
    assert "tls-watchdog is down" in result.signal_draft
    assert "restarted" not in result.signal_draft
