"""Three failed probes in a row write the deadman flag and page once, straight
to Signal; a refused bearer counts as a failure; the first good probe clears it.

WHAT IT PINS. `alerts.deadman.decide` and `run_cycle`, `alerts.assistant_deadman.main`,
and `alert_relay.assistant_door.check_assistant` against a real loopback HTTP
server standing in for the assistant.

WHERE THE EXPECTED ANSWERS COME FROM. The contract in the deadman docstrings:
threshold 3 (about three minutes at the 60 s timer), one page per state change,
pages never through the assistant (`signal_direct=True`), and a 401 on the
alert door is as dead as no answer, because an assistant can answer `/health`
while refusing every delivery.
"""
from __future__ import annotations

from infra.observability.alert_relay import assistant_door
from infra.observability.alerts import assistant_deadman, deadman


def test_one_or_two_misses_are_not_down_and_the_third_pages_once() -> None:
    verdicts = []
    failures = 0
    for _ in range(5):
        verdict = deadman.decide(healthy=False, failures_before=failures)
        failures = verdict.failures
        verdicts.append(verdict)
    assert [v.down for v in verdicts] == [False, False, True, True, True]
    assert [v.page for v in verdicts] == ["", "", "down", "", ""]
    back = deadman.decide(healthy=True, failures_before=failures)
    assert (back.down, back.page, back.failures) == (False, "up", 0)


def test_the_flag_is_written_on_the_third_failure_and_cleared_by_the_first_success(
    monkeypatch, isolated_state
) -> None:
    pages: list[tuple[str, dict]] = []

    def record(subject, body, **kwargs):
        pages.append((subject, kwargs))
        return {"signal": True}

    monkeypatch.setattr(assistant_deadman, "fan_out", record)
    monkeypatch.setattr(assistant_deadman, "probe", lambda: (False, "alert-relay did not answer"))
    flag = isolated_state / "assistant-down"

    for cycle in range(1, 6):
        assistant_deadman.main()
        assert flag.exists() is (cycle >= 3), f"cycle {cycle}"
    assert len(pages) == 1, "a five-minute outage paged more than once"
    assert "down" in pages[0][0] and pages[0][1].get("signal_direct") is True

    monkeypatch.setattr(assistant_deadman, "probe", lambda: (True, ""))
    assistant_deadman.main()
    assert not flag.exists()
    assert len(pages) == 2 and "back" in pages[1][0]


def test_a_page_that_reached_nobody_is_offered_again_next_cycle(monkeypatch) -> None:
    attempts: list[str] = []

    def unreachable(subject, body, **kwargs):
        attempts.append(subject)
        return {"signal": False}

    for _ in range(4):
        deadman.run_cycle("x", healthy=False, down_message=("down", ""), up_message=("up", ""),
                          send=unreachable, now=1_760_000_000.0)
    assert len(attempts) == 2, "a page nobody received stamped the cooldown"


def test_a_door_that_answers_health_but_refuses_the_bearer_is_reported_as_refusing(
    monkeypatch, fake_server
) -> None:
    assistant = fake_server({"/webhook/alertmanager": 401})
    monkeypatch.setenv("ASSISTANT_URL", assistant.url)
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", "s3cret")
    answer = assistant_door.check_assistant()
    assert answer["alive"] is True and answer["accepts"] is False
    posted = assistant.posts_to("/webhook/alertmanager")
    assert posted and posted[0]["auth"] == "Bearer s3cret"
    assert posted[0]["json"] == {"version": "4", "alerts": []}, "the check must carry no alerts"


def test_a_door_that_takes_the_empty_envelope_is_healthy(monkeypatch, fake_server) -> None:
    assistant = fake_server()
    monkeypatch.setenv("ASSISTANT_URL", assistant.url)
    assert assistant_door.check_assistant()["accepts"] is True
