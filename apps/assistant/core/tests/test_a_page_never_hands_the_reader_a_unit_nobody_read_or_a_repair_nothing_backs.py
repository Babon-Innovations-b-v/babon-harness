"""A page never hands the reader a unit nobody read or a repair nothing backs.

WHAT IT PINS. `core.triage.triage` and `core.voice.render`, across their
public interfaces, with the model stubbed. The backup alert's pointer to
its evidence reaches the model; a draft naming a unit neither the alert nor a
tool result named, or asking for a state change nothing read backs, is nudged
once and then loses those sentences, while a hyphenated English word before
"service" is not taken for a unit; and the container's voice no longer teaches
"I can't read it from here".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The alert's
annotations are read from operational-rules.yml as Prometheus would render
them. The drafts are two pages of the shape the model wrote; whether
"backup-index-push" or "restarted" is backed is read off the alert payload and
the (empty) reads by eye.

"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

#: The alert as Prometheus renders it: a summary, a description and the
#: first_action pointer to its evidence, which is for the model and not for
#: the reader.
_ANNOTATIONS = {
    "summary": "The nightly backup index has not been refreshed for 30m",
    "first_action": (
        "db_query `SELECT created_at, detail FROM ops_activity WHERE "
        "action_type='backup_index' ORDER BY id DESC LIMIT 5`: detail.outcome "
        "names which step failed"
    ),
    "description": (
        "Every cycle builds the backup index and copies it into place, and for "
        "30 minutes the cycles that tried have failed at one of the two."
    ),
}
_UNIT_PAGE = (
    "The nightly backup index is 6h behind. Needs a look at the server-side "
    "backup-index-push service log."
)
_REMEDY_PAGE = "All 8 tls-watchdog targets dark since 16:21. Need the watchdog restarted."


def _repo_index_annotations() -> dict[str, str]:
    return dict(_ANNOTATIONS)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools
    from apps.assistant.core.triage import Alert, triage

    shown: list = []
    script = {"draft": _UNIT_PAGE}

    def fake_run(*, messages, **_ignored):
        shown.append(messages[-1]["content"])
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(shown)}", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "lagging", "signal_draft": script["draft"]},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run(annotations: dict[str, str]):
        return triage(
            Alert(
                fingerprint="8585a3cfcf246c8b", status="firing",
                labels={"alertname": "TargetDown", "severity": "warning",
                        "component": "backup-index"},
                annotations=annotations,
                starts_at="2026-03-10T09:58:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, shown=shown, script=script)


def test_the_alerts_pointer_to_its_evidence_reaches_the_model(pod) -> None:
    pod.run(_repo_index_annotations())
    assert "where_to_look_not_for_the_reader" in pod.shown[0]
    assert "ops_activity" in pod.shown[0]


def test_a_unit_nothing_read_is_asked_about_then_left_out(pod) -> None:
    result = pod.run(_repo_index_annotations())
    assert len(pod.shown) == 2
    assert "backup-index-push" in str(pod.shown[1])
    assert "backup-index-push" not in (result.signal_draft or "")


def test_a_repair_nothing_backs_is_asked_about_then_left_out(pod) -> None:
    pod.script["draft"] = _REMEDY_PAGE
    result = pod.run({"summary": "Prometheus target tls-watchdog down 15m"})
    assert len(pod.shown) == 2
    assert "restarted" not in (result.signal_draft or "")


def test_the_pods_voice_no_longer_teaches_giving_up_on_the_journal() -> None:
    from apps.assistant.core import voice

    assert "can't read it from here" not in " ".join(voice.render().split())


@pytest.mark.parametrize(
    "sentence",
    [
        "Webapp is down; the health-check service answers 502.",
        "The third-party service is slow.",
        "It is a long-running service.",
    ],
)
def test_hyphenated_english_before_service_is_not_a_unit(sentence) -> None:
    from apps.assistant.core import claims

    assert claims.unread_units(sentence, "") == []


def test_a_true_page_keeps_its_symptom_line_about_a_hyphenated_service(pod) -> None:
    pod.script["draft"] = "Webapp is down; the health-check service answers 502."
    result = pod.run({"summary": "Webapp probe failing 10m"})
    assert len(pod.shown) == 1
    assert result.signal_draft == pod.script["draft"]
