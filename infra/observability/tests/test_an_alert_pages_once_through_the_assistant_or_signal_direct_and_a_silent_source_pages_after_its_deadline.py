"""An alert pages once, through the assistant or Signal direct, and a source gone silent pages after its deadline and then on a fixed beat.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A page goes to the assistant's notify door; a deadman page and a page the
door will not take go straight to signal-cli, from the bot to the owner.

WHAT IT PINS. `alerts.notify.fan_out` and `send_signal`, against two real
loopback HTTP servers standing in for the assistant and for signal-cli's REST
API. What is checked is what those servers received.

WHERE THE EXPECTED ANSWERS COME FROM. The routing contract in notify's
docstring and the signal-cli REST shape (`POST /v2/send` with `number`,
`recipients`, `message`). A long body is split, never cut, because the thing
to do is usually its last line.

A failing harness unit pages once per distinct failure, names the line its
failing run ended on, and is not paged over Signal when Signal is what failed.

WHAT IT PINS. `alerts.systemd_failure_notify`: `signature`, `error_line` and
`main`. `main` shells out to systemctl and journalctl; those probes are
replaced by the text they return, and `fan_out` by a recorder.

WHERE THE EXPECTED ANSWERS COME FROM. The journal texts below are written in
the shape `journalctl --output=short-iso` prints. Two runs of one failure
differ only in timestamp, PID and logging stamp, so they must share a
signature; `http 500` and `http 401` are different failures and must not. The
error line is the last line the program wrote before systemd's own lines,
read by eye.

Three failed probes in a row write the deadman flag and page once, straight
to Signal; a refused bearer counts as a failure; the first good probe clears it.

WHAT IT PINS. `alerts.deadman.decide` and `run_cycle`, `alerts.assistant_deadman.main`,
and `alert_relay.assistant_door.check_assistant` against a real loopback HTTP
server standing in for the assistant.

WHERE THE EXPECTED ANSWERS COME FROM. The contract in the deadman docstrings:
threshold 3 (about three minutes at the 60 s timer), one page per state change,
pages never through the assistant (`signal_direct=True`), and a 401 on the
alert door is as dead as no answer, because an assistant can answer `/health`
while refusing every delivery.

The dead-man's switch pages when the Watchdog heartbeat has been unseen for an
hour, then at most hourly, and reads the heartbeat time in UTC.

WHAT IT PINS. `alerts.dead_mans_switch.should_page` and `watchdog_seen_ts`, the
latter against a real loopback server answering Alertmanager's `/api/v2/alerts`.

WHERE THE EXPECTED ANSWERS COME FROM. Its docstring: threshold 3600 s, repage
3600 s, a heartbeat never seen pages. Alertmanager writes `updatedAt` in UTC
(`...Z`), so 2026-10-01T00:00:00Z is epoch 1790812800 whatever the test
machine's timezone is.
"""
from __future__ import annotations

import inspect


# From a page goes through the assistant and falls back to signal direct.

import pytest


from infra.observability.alerts import notify


BOT = "+10000000001"


OWNER = "+10000000002"


@pytest.fixture
def roads(monkeypatch, fake_server):
    assistant = fake_server()
    signal_cli = fake_server()
    monkeypatch.setenv("ASSISTANT_URL", assistant.url)
    monkeypatch.setenv("SIGNAL_CLI_URL", signal_cli.url)
    monkeypatch.setenv("SIGNAL_BOT_NUMBER", BOT)
    monkeypatch.setenv("SIGNAL_ALLOWLIST", f"{OWNER},+10000000003")
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("NOTIFY_GATEWAY_RETRY_S", "0")
    return assistant, signal_cli


def _an_ordinary_page_goes_to_the_assistant_with_its_facts(roads) -> None:
    assistant, signal_cli = roads
    result = notify.fan_out("Unit failed: harness-backup.service", "body", facts={"exit_code": 1})
    assert result == {"signal": True}
    posted = assistant.posts_to("/webhook/notify")
    assert len(posted) == 1 and posted[0]["auth"] == "Bearer s3cret"
    assert posted[0]["json"]["facts"] == {"exit_code": 1}
    assert signal_cli.requests == []


def _a_deadman_page_never_touches_the_assistant(roads) -> None:
    assistant, signal_cli = roads
    assert notify.fan_out("Assistant is down", "detail", signal_direct=True) == {"signal": True}
    assert assistant.requests == []
    sent = signal_cli.posts_to("/v2/send")
    assert [r["json"] for r in sent] == [
        {"number": BOT, "recipients": [OWNER], "message": "Assistant is down\n\ndetail"}
    ]


def _a_door_that_keeps_refusing_is_retried_then_the_page_goes_direct(roads, monkeypatch) -> None:
    assistant, signal_cli = roads
    assistant.statuses["/webhook/notify"] = 503
    monkeypatch.setenv("NOTIFY_GATEWAY_ATTEMPTS", "3")
    assert notify.fan_out("Disk almost full", "/ is 91% full")["signal"] is True
    assert len(assistant.posts_to("/webhook/notify")) == 3
    assert signal_cli.posts_to("/v2/send")[0]["json"]["message"].endswith("/ is 91% full")


def _no_road_at_all_is_reported_not_raised(monkeypatch, fake_server) -> None:
    monkeypatch.setenv("SIGNAL_CLI_URL", fake_server({"/v2/send": 500}).url)
    monkeypatch.setenv("SIGNAL_BOT_NUMBER", BOT)
    monkeypatch.setenv("SIGNAL_RECIPIENT", OWNER)
    assert notify.fan_out("x", "y", signal_direct=True) == {"signal": False}


def _a_long_body_is_split_and_its_last_line_arrives() -> None:
    body = "\n".join(f"line {index} " + "x" * 60 for index in range(100)) + "\nDO THIS LAST"
    pieces = notify.compose_signal_pieces("subject", body)
    assert len(pieces) > 1
    assert all(len(piece) <= notify.SIGNAL_PIECE_MAX_CHARS for piece in pieces)
    assert pieces[-1].endswith("DO THIS LAST")
    assert "".join(pieces).replace("\n", "") == f"subject\n\n{body}".replace("\n", "")

# From one unit outage pages once and names the line it failed on.

from infra.observability.alerts import systemd_failure_notify as handler


UNIT = "harness-backup.service"


def _run(stamp: str, pid: int, status: int) -> str:
    return (
        f"2026-10-01T{stamp}+00:00 harness-vm python3[{pid}]: "
        f"2026-10-01 {stamp},016 INFO uploading dump\n"
        f"2026-10-01T{stamp}+00:00 harness-vm python3[{pid}]: "
        f"2026-10-01 {stamp},017 ERROR upload failed: http {status}\n"
        f"2026-10-01T{stamp}+00:00 harness-vm systemd[1]: "
        f"{UNIT}: Main process exited, code=exited, status=1/FAILURE\n"
        f"2026-10-01T{stamp}+00:00 harness-vm systemd[1]: {UNIT}: Consumed 1.234s CPU time."
    )


FIRST_500 = _run("03:00:01", 4101, 500)


SECOND_500 = _run("04:00:02", 5233, 500)


A_401 = _run("05:00:01", 6377, 401)


def _two_runs_of_one_outage_share_a_signature() -> None:
    assert handler.signature(UNIT, FIRST_500) == handler.signature(UNIT, SECOND_500)


def _a_different_status_code_is_a_different_failure() -> None:
    assert handler.signature(UNIT, FIRST_500) != handler.signature(UNIT, A_401)


def _the_error_line_is_the_programs_last_line_not_systemds() -> None:
    assert handler.error_line(FIRST_500) == "ERROR upload failed: http 500"
    assert handler.error_line(None) is None


def _main(monkeypatch, unit: str, run_text: str) -> list[tuple[str, str, dict]]:
    monkeypatch.setattr(handler, "_was_intentionally_stopped", lambda _unit: False)
    monkeypatch.setattr(handler, "_journal_tail", lambda _unit: handler.JournalTail(run_text, read=True))
    monkeypatch.setattr(handler, "_failing_run_text", lambda _unit: run_text)
    monkeypatch.setattr(handler, "_exit_status", lambda _unit: 1)
    sent: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(handler, "fan_out", lambda subject, body, **kw: sent.append((subject, body, kw)))
    handler.main([unit])
    return sent


def _the_first_failure_pages_with_its_reason_and_the_repeat_is_held(monkeypatch) -> None:
    sent = _main(monkeypatch, UNIT, FIRST_500)
    assert len(sent) == 1
    subject, body, kwargs = sent[0]
    assert UNIT in subject and "Reason: ERROR upload failed: http 500" in body
    assert kwargs["facts"]["error_line"] == "ERROR upload failed: http 500"
    assert kwargs["facts"]["exit_code"] == 1
    assert _main(monkeypatch, UNIT, SECOND_500) == [], "the same failure paged twice inside the hold"
    assert len(_main(monkeypatch, UNIT, A_401)) == 1, "a new failure was swallowed by the old hold"


def _the_signal_canary_failing_is_not_paged_over_signal(monkeypatch, unit) -> None:
    assert _main(monkeypatch, unit, FIRST_500) == []


def _an_assistant_unit_is_quiet_while_the_deadman_has_already_paged(monkeypatch, isolated_state) -> None:
    (isolated_state / "assistant-down").write_text("1")
    assert _main(monkeypatch, "harness-assistant-deadman.service", FIRST_500) == []

# From the assistant deadman flags after three failures and pages once.

from infra.observability.alert_relay import assistant_door


from infra.observability.alerts import assistant_deadman, deadman


def _one_or_two_misses_are_not_down_and_the_third_pages_once() -> None:
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


def _the_flag_is_written_on_the_third_failure_and_cleared_by_the_first_success(
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


def _a_page_that_reached_nobody_is_offered_again_next_cycle(monkeypatch) -> None:
    attempts: list[str] = []

    def unreachable(subject, body, **kwargs):
        attempts.append(subject)
        return {"signal": False}

    for _ in range(4):
        deadman.run_cycle("x", healthy=False, down_message=("down", ""), up_message=("up", ""),
                          send=unreachable, now=1_760_000_000.0)
    assert len(attempts) == 2, "a page nobody received stamped the cooldown"


def _a_door_that_answers_health_but_refuses_the_bearer_is_reported_as_refusing(
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


def _a_door_that_takes_the_empty_envelope_is_healthy(monkeypatch, fake_server) -> None:
    assistant = fake_server()
    monkeypatch.setenv("ASSISTANT_URL", assistant.url)
    assert assistant_door.check_assistant()["accepts"] is True

# From the dead mans switch pages after an hour of silence and then hourly.

import json


import threading


import time


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


from infra.observability.alerts.dead_mans_switch import should_page, watchdog_seen_ts


HOUR = 3600


def _when_it_pages(seen_ago, paged_ago, expected) -> None:
    now = 10_000_000.0
    assert should_page(
        last_seen_ts=None if seen_ago is None else now - seen_ago,
        last_paged_ts=None if paged_ago is None else now - paged_ago,
        now=now,
        silent_threshold_s=HOUR,
        repage_interval_s=HOUR,
    ) is expected


@pytest.fixture
def far_timezone(monkeypatch):
    """Run in a timezone nine hours from UTC, so a local-time read is visibly wrong."""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _the_heartbeat_time_is_read_from_alertmanager_in_utc(far_timezone) -> None:
    alerts = [
        {"labels": {"alertname": "DiskAlmostFull"}, "updatedAt": "2026-10-02T00:00:00.000Z"},
        {"labels": {"alertname": "Watchdog"}, "updatedAt": "2026-10-01T00:00:00.000Z"},
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(alerts).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert watchdog_seen_ts(url, "Watchdog") == 1790812800
    finally:
        server.shutdown()
        server.server_close()


def _an_unreachable_alertmanager_reads_as_silence() -> None:
    assert watchdog_seen_ts("http://127.0.0.1:9", "Watchdog") is None


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
    *_cases(_an_ordinary_page_goes_to_the_assistant_with_its_facts),
    *_cases(_a_deadman_page_never_touches_the_assistant),
    *_cases(_a_door_that_keeps_refusing_is_retried_then_the_page_goes_direct),
    *_cases(_no_road_at_all_is_reported_not_raised),
    *_cases(_a_long_body_is_split_and_its_last_line_arrives),
    *_cases(_two_runs_of_one_outage_share_a_signature),
    *_cases(_a_different_status_code_is_a_different_failure),
    *_cases(_the_error_line_is_the_programs_last_line_not_systemds),
    *_cases(_the_first_failure_pages_with_its_reason_and_the_repeat_is_held),
    *_cases(_the_signal_canary_failing_is_not_paged_over_signal, "unit", sorted(handler.SIGNAL_UNDER_TEST_UNITS)),
    *_cases(_an_assistant_unit_is_quiet_while_the_deadman_has_already_paged),
    *_cases(_one_or_two_misses_are_not_down_and_the_third_pages_once),
    *_cases(_the_flag_is_written_on_the_third_failure_and_cleared_by_the_first_success),
    *_cases(_a_page_that_reached_nobody_is_offered_again_next_cycle),
    *_cases(_a_door_that_answers_health_but_refuses_the_bearer_is_reported_as_refusing),
    *_cases(_a_door_that_takes_the_empty_envelope_is_healthy),
    *_cases(_when_it_pages, 
    ("seen_ago", "paged_ago", "expected"),
    [
        (60, None, False),         # heartbeat fresh
        (HOUR - 1, None, False),   # just under the threshold
        (HOUR, None, True),        # silent for an hour
        (3 * HOUR, 10, False),     # paged ten seconds ago: hold
        (3 * HOUR, HOUR, True),    # an hour since the last page: nag
        (None, None, True),        # never seen, never paged
        (None, 600, False),        # never seen, paged ten minutes ago
    ],
),
    *_cases(_the_heartbeat_time_is_read_from_alertmanager_in_utc),
    *_cases(_an_unreachable_alertmanager_reads_as_silence),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_an_alert_pages_once_through_the_assistant_or_signal_direct_and_a_silent_source_pages_after_its_deadline(scenario, given, uses, request):
    """An alert pages once, through the assistant or Signal direct, and a source gone silent pages after its deadline and then on a fixed beat: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
