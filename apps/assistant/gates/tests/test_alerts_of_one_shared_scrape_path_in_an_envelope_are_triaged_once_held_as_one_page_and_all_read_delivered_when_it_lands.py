"""Alerts of one shared scrape path in an envelope are triaged once, held as
one page, and all read delivered when it lands.

WHAT IT PINS. The `/webhook/alertmanager` route with `core.triage.triage_envelope`
behind it, and `core.page_hold.release`, across their public interfaces. The
model is a stub that counts its calls and always pages. A group page is not
dropped as old news while a sibling it speaks for still fires.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The envelope is
a small fixture: six TargetDown scrape-target alerts on
three blackbox jobs, all carrying `scrape_via=k8s-tunnel` as the rule now sets
it, plus one unrelated TargetDown on a job that carries no scrape_via.
That is two causes, so two model calls and two held pages; the leader of the
tunnel group is the lowest fingerprint, read off the fixture list with `min`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

_SECRET = "test-bearer"
_TUNNEL = [
    ("probes-tls", "https://alerts.example.org", "c408782c00000001"),
    ("probes-tls", "https://metrics.example.org", "7cf53cfba607fb7a"),
    ("probes-health", "https://docs.example.org/healthz", "2fd5916c58edc4c3"),
    ("probes-health", "https://status.example.org/healthz", "5164a40900000002"),
    ("probes-http", "https://app.example.org/", "b0228d9600000003"),
    ("probes-http", "https://example.org/", "0e1d2c3b4a596877"),
]
_LONE = ("app-exporter", "app-exporter:8000", "9c620cfb66dd863e")
_LEADER = min(fingerprint for _, _, fingerprint in _TUNNEL)


def _alert(job: str, instance: str, fingerprint: str, via: str | None) -> dict:
    labels = {
        "alertname": "TargetDown", "severity": "warning",
        "component": "scrape-target", "job": job, "instance": instance,
    }
    if via:
        labels["scrape_via"] = via
    return {
        "status": "firing", "labels": labels,
        "annotations": {"summary": f"Prometheus target {job}/{instance} down 15m"},
        "startsAt": "2026-10-22T14:00:00Z", "endsAt": "0001-01-01T00:00:00Z",
        "fingerprint": fingerprint,
    }


def _envelope(tunnel: list[tuple[str, str, str]]) -> dict:
    alerts = [_alert(*entry, via="k8s-tunnel") for entry in tunnel]
    alerts.append(_alert(*_LONE, via=None))
    return {"version": "4", "status": "firing", "alerts": alerts}


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh table, a bearer, a model stub that pages, and a Signal stub."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    from fastapi.testclient import TestClient

    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.gates import app as gate_app

    calls: list[str] = []

    def fake_run(*, messages, **_ignored):
        calls.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich", "reason": "targets dark",
                "signal_draft": f"Scrape targets dark ({len(calls)}).",
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)
    client = TestClient(gate_app.app)

    def post(tunnel: list[tuple[str, str, str]]):
        response = client.post(
            "/webhook/alertmanager", json=_envelope(tunnel),
            headers={"Authorization": f"Bearer {_SECRET}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return SimpleNamespace(post=post, calls=calls, state=state, page_hold=page_hold)


def test_one_cause_is_one_model_call_and_one_held_page(pod) -> None:
    pod.post(_TUNNEL)
    assert len(pod.calls) == 2
    held = pod.state.pending_pages()
    assert sorted(row["key"] for row in held) == sorted([_LEADER, _LONE[2]])
    followers = [
        row for row in pod.state.list_recent_alerts(50)
        if row["reason"] == f"same cause as {_LEADER}"
    ]
    assert len(followers) == len(_TUNNEL) - 1


def test_a_resend_in_another_order_folds_into_the_same_held_page(pod, monkeypatch) -> None:
    monkeypatch.setattr(pod.state, "dedup_check_and_touch", lambda fingerprint: False)
    pod.post(_TUNNEL)
    pod.post(list(reversed(_TUNNEL)))
    keys = {row["key"] for row in pod.state.pending_pages()}
    assert keys == {_LEADER, _LONE[2]}


def test_every_fingerprint_of_the_cause_reads_delivered_once_the_page_lands(pod) -> None:
    from apps.assistant.core.state.alerts import last_delivered_at

    pod.post(_TUNNEL)
    # 14:00 local: outside quiet hours and past the morning gate.
    pod.page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
    for _, _, fingerprint in _TUNNEL:
        assert last_delivered_at(fingerprint), fingerprint


def test_the_leader_recovering_alone_does_not_drop_the_group_page(pod) -> None:
    pod.post(_TUNNEL)
    pod.state.record_alert(
        fingerprint=_LEADER, name="TargetDown", severity="warning",
        status="resolved", decision="silent", reason="fixture",
        signal_sent=False, dead_letter=False,
    )
    pod.page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
    assert pod.state.last_released_text(_LEADER), "the group page was dropped"
