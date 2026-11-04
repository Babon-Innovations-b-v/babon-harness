"""The relay hands every alert group to the assistant, and speaks itself only

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

while the assistant is verified down, once per group, saying what fired.

WHAT IT PINS. `alert_relay.relay.relay_payload` with the real deadman-flag
read (`assistant_gate`) and the real `Deduper`. Only the two network calls are
stood in for, through the injection points the function declares.

WHERE THE EXPECTED ANSWERS COME FROM. The relay's contract, written by hand
here and not imported: the flag counts as fresh for 300 s (the deadman rewrites
it every 60 s), a (fingerprint, status) pair seen within 1,800 s is a repeat,
and a group is one message. Deciding wrong is silent either way: speak while the
assistant is up and every alert arrives twice; stay quiet while it is down and
the outage reaches nobody.
"""
from __future__ import annotations

import inspect


# From the relay hands alerts to the assistant and speaks only when it is down.

import os


import pytest


from infra.observability.alert_relay.assistant_gate import assistant_is_down, flag_mount_present


from infra.observability.alert_relay.deduper import Deduper


from infra.observability.alert_relay.relay import relay_payload


T0 = 1_760_000_000.0


FLAG_FRESH_FOR_S = 300


REPEAT_WINDOW_S = 1800


AM_RETRY_S = 30


class Roads:
    """The two collaborators: the assistant door and the raw Signal road."""

    def __init__(self) -> None:
        self.forwarded: list[dict] = []
        self.messages: list[tuple[str, str]] = []

    def forward(self, payload: dict) -> None:
        self.forwarded.append(payload)

    def fan_out(self, subject: str, body: str) -> dict[str, bool]:
        self.messages.append((subject, body))
        return {"signal": True}


@pytest.fixture
def flag(isolated_state):
    """The flag's path, its directory present and the flag absent: all is fine."""
    return isolated_state / "assistant-down"


def _down_since(flag, when: float) -> None:
    flag.write_text("1\n")
    os.utime(flag, (when, when))


def _alert(fingerprint: str, *, status: str = "firing", summary: str = "", first_action: str = "",
           instance: str = "", runbook: str = "") -> dict:
    return {
        "fingerprint": fingerprint,
        "status": status,
        "startsAt": "2026-10-01T02:14:00.000Z",
        "labels": {"alertname": "DiskAlmostFull", "severity": "warning", "instance": instance},
        "annotations": {"summary": summary, "first_action": first_action, "runbook_url": runbook},
    }


def _payload(*alerts: dict) -> dict:
    return {"version": "4", "groupKey": '{}:{alertname="DiskAlmostFull"}', "alerts": list(alerts)}


GROUP = _payload(
    _alert("a1", summary="/ is 91% full", first_action="prune old images", instance="node-a",
           runbook="https://docs.example.org/runbooks/disk"),
    _alert("b2", summary="/data is 88% full", first_action="prune old images", instance="node-b",
           runbook="https://docs.example.org/runbooks/disk"),
)


def _relay(payload, roads, deduper, now):
    return relay_payload(payload, forward=roads.forward, fan_out=roads.fan_out, deduper=deduper, now=now)


def _while_the_assistant_answers_the_group_is_handed_over_whole_and_nothing_is_sent(flag) -> None:
    roads = Roads()
    outcomes = _relay(GROUP, roads, Deduper(), now=T0)
    assert roads.forwarded == [GROUP], "the assistant did not get the group exactly once, unchanged"
    assert roads.messages == [], "the relay spoke while the assistant was up"
    assert {(o.fingerprint, o.route) for o in outcomes} == {("a1", "assistant"), ("b2", "assistant")}


def _a_refused_hand_over_raises_so_alertmanager_retries(flag) -> None:
    roads = Roads()

    def refuse(payload):
        raise OSError("HTTP 401")

    with pytest.raises(OSError):
        relay_payload(GROUP, forward=refuse, fan_out=roads.fan_out, deduper=Deduper(), now=T0)


def _while_the_assistant_is_down_one_message_carries_every_alert_and_its_first_action(flag) -> None:
    _down_since(flag, T0)
    roads = Roads()
    outcomes = _relay(GROUP, roads, Deduper(), now=T0)
    assert roads.forwarded == []
    assert len(roads.messages) == 1, f"two alerts produced {len(roads.messages)} messages"
    subject, body = roads.messages[0]
    assert "DiskAlmostFull" in subject and "warning" in subject
    for fact in ("/ is 91% full", "/data is 88% full", "node-a", "node-b", "prune old images",
                 "https://docs.example.org/runbooks/disk"):
        assert fact in body, f"the only record of the outage does not say {fact!r}"
    assert {o.route for o in outcomes} == {"signal"}


def _a_stale_flag_means_the_deadman_stopped_writing_not_that_the_assistant_is_down(
    flag, flag_age_s, raw
) -> None:
    _down_since(flag, T0 - flag_age_s)
    roads = Roads()
    _relay(GROUP, roads, Deduper(), now=T0)
    assert bool(roads.messages) is raw
    assert bool(roads.forwarded) is not raw


def _alertmanager_repeating_a_group_does_not_repeat_the_message_until_half_an_hour_has_passed(flag) -> None:
    _down_since(flag, T0)
    roads, deduper = Roads(), Deduper()
    _relay(GROUP, roads, deduper, now=T0)
    for repeat in range(1, 6):
        moment = T0 + repeat * AM_RETRY_S
        _down_since(flag, moment)
        _relay(GROUP, roads, deduper, now=moment)
    assert len(roads.messages) == 1
    later = T0 + REPEAT_WINDOW_S + 1
    _down_since(flag, later)
    _relay(GROUP, roads, deduper, now=later)
    assert len(roads.messages) == 2, "an incident still firing half an hour later was never mentioned again"


def _an_alert_clearing_is_never_muted_by_the_firing_before_it(flag) -> None:
    _down_since(flag, T0)
    roads, deduper = Roads(), Deduper()
    _relay(GROUP, roads, deduper, now=T0)
    cleared = _payload(_alert("a1", status="resolved", summary="disk back under 85%"),
                       _alert("b2", status="resolved", summary="disk back under 85%"))
    _down_since(flag, T0 + 60)
    _relay(cleared, roads, deduper, now=T0 + 60)
    assert len(roads.messages) == 2
    assert "RESOLVED" in roads.messages[-1][0] and "disk back under 85%" in roads.messages[-1][1]


def _a_relay_that_cannot_see_the_flag_directory_can_say_so(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_DOWN_FLAG_PATH", str(tmp_path / "no-such-mount" / "assistant-down"))
    assert assistant_is_down(now=T0) is False
    assert flag_mount_present() is False


def _no_alert_is_lost_between_the_webhook_and_the_message(flag) -> None:
    """Every fingerprint comes back once, and every sent alert's summary is in the message."""
    payloads = [
        _payload(_alert("solo", summary="one thing broke")),
        _payload(*[_alert(f"many{i}", summary=f"disk {i} at 9{i}%") for i in range(12)]),
        _payload(_alert("m1", summary="still down"), _alert("m2", status="resolved", summary="back up")),
        _payload(_alert("bare"), _alert("unicode", summary="cert for café.example.org expires in 3 d")),
        _payload({"status": "firing", "labels": {}, "annotations": {}}, _alert("survivor", summary="kept")),
    ]
    for index, payload in enumerate(payloads):
        moment = T0 + index * 10_000
        _down_since(flag, moment)
        roads = Roads()
        outcomes = _relay(payload, roads, Deduper(), now=moment)
        expected = sorted(a["fingerprint"] for a in payload["alerts"] if a.get("fingerprint"))
        assert sorted(o.fingerprint for o in outcomes) == expected
        body = roads.messages[0][1]
        for alert in payload["alerts"]:
            summary = alert["annotations"].get("summary")
            if alert.get("fingerprint") and summary:
                assert summary in body


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_while_the_assistant_answers_the_group_is_handed_over_whole_and_nothing_is_sent),
    *_cases(_a_refused_hand_over_raises_so_alertmanager_retries),
    *_cases(_while_the_assistant_is_down_one_message_carries_every_alert_and_its_first_action),
    *_cases(_a_stale_flag_means_the_deadman_stopped_writing_not_that_the_assistant_is_down, 
    ("flag_age_s", "raw"),
    [(0, True), (FLAG_FRESH_FOR_S - 1, True), (FLAG_FRESH_FOR_S, True),
     (FLAG_FRESH_FOR_S + 1, False), (3600, False)],
),
    *_cases(_alertmanager_repeating_a_group_does_not_repeat_the_message_until_half_an_hour_has_passed),
    *_cases(_an_alert_clearing_is_never_muted_by_the_firing_before_it),
    *_cases(_a_relay_that_cannot_see_the_flag_directory_can_say_so),
    *_cases(_no_alert_is_lost_between_the_webhook_and_the_message),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_relay_hands_alerts_to_the_assistant_and_speaks_only_when_it_is_down(scenario, given, uses, request):
    """The relay hands every alert group to the assistant, and speaks itself only: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
