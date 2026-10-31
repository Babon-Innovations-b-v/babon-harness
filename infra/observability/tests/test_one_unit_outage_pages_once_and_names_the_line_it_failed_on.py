"""A failing harness unit pages once per distinct failure, names the line its
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
"""
from __future__ import annotations

import pytest

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


def test_two_runs_of_one_outage_share_a_signature() -> None:
    assert handler.signature(UNIT, FIRST_500) == handler.signature(UNIT, SECOND_500)


def test_a_different_status_code_is_a_different_failure() -> None:
    assert handler.signature(UNIT, FIRST_500) != handler.signature(UNIT, A_401)


def test_the_error_line_is_the_programs_last_line_not_systemds() -> None:
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


def test_the_first_failure_pages_with_its_reason_and_the_repeat_is_held(monkeypatch) -> None:
    sent = _main(monkeypatch, UNIT, FIRST_500)
    assert len(sent) == 1
    subject, body, kwargs = sent[0]
    assert UNIT in subject and "Reason: ERROR upload failed: http 500" in body
    assert kwargs["facts"]["error_line"] == "ERROR upload failed: http 500"
    assert kwargs["facts"]["exit_code"] == 1
    assert _main(monkeypatch, UNIT, SECOND_500) == [], "the same failure paged twice inside the hold"
    assert len(_main(monkeypatch, UNIT, A_401)) == 1, "a new failure was swallowed by the old hold"


@pytest.mark.parametrize("unit", sorted(handler.SIGNAL_UNDER_TEST_UNITS))
def test_the_signal_canary_failing_is_not_paged_over_signal(monkeypatch, unit) -> None:
    assert _main(monkeypatch, unit, FIRST_500) == []


def test_an_assistant_unit_is_quiet_while_the_deadman_has_already_paged(monkeypatch, isolated_state) -> None:
    (isolated_state / "assistant-down").write_text("1")
    assert _main(monkeypatch, "harness-assistant-deadman.service", FIRST_500) == []
