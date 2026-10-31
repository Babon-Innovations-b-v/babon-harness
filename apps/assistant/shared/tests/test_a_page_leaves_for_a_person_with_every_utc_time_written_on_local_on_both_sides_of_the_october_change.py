"""A page leaves for a person with every UTC time on the local clock, with
the offset of the day that time falls on.

WHAT IT PINS. `shared.local_time.in_local_time` and the one seam that calls it,
`shared.signal.send`: a body sent with an empty subject (the assistant's own voice,
every page, pen message and teammate message) reaches the transport with its
"HH:MM UTC", "HH:MM:SS UTC", "HH:MMZ" and ISO "...Z" times rewritten as
"16:12 local (CEST)"; a body sent under a subject (a machine page)
reaches it byte for byte, and a time naming no zone is never touched.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. EU summer time
ends at 01:00 UTC on the last Sunday of October, 25 October 2026: before that
local is UTC+2 (CEST), from that moment UTC+1 (CET). So 14:12 UTC on 24
October is 16:12 CEST, 13:56 UTC on 26 October is 14:56 CET, and on the day
itself 00:30 UTC is 02:30 CEST while 01:30 UTC is 02:30 CET. Each expected
string is that sum, done by hand.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apps.assistant.shared import local_time, signal

_SUMMER = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
_CHANGE_DAY = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)
_WINTER = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


def test_every_utc_shape_is_written_on_locals_summer_clock() -> None:
    """The four shapes a model or a receipt writes, the day before the change."""
    text = (
        "down since 14:12 UTC, first seen 14:12:05 UTC, retried 14:20Z; "
        "deploy 2026-10-24T13:01:00Z"
    )
    assert local_time.in_local_time(text, _SUMMER) == (
        "down since 16:12 local time (CEST), first seen 16:12:05 local "
        "time (CEST), retried 16:20 local time (CEST); "
        "deploy 15:01:00 local time (CEST)"
    )


def test_a_utc_time_after_the_change_is_written_on_the_winter_clock() -> None:
    """A page written in October, had it been sent after the change."""
    assert (
        local_time.in_local_time("status dashboard down since 13:56 UTC", _WINTER)
        == "status dashboard down since 14:56 local time (CET)"
    )


def test_on_the_day_of_the_change_each_time_takes_its_own_offset() -> None:
    """02:30 happens twice on 25 October; the zone name tells the two apart."""
    assert local_time.in_local_time("00:30 UTC, then 01:30 UTC", _CHANGE_DAY) == (
        "02:30 local time (CEST), then 02:30 local time (CET)"
    )


def test_a_range_marked_utc_once_moves_both_ends_and_keeps_its_length() -> None:
    """"14:00-15:00 UTC" is one hour; converting only the marked end made it three."""
    assert local_time.in_local_time("window 14:00\u201315:00 UTC", _SUMMER) == (
        "window 16:00\u201317:00 local time (CEST)"
    )
    assert local_time.in_local_time("between 14:00 and 15:00 UTC", _SUMMER) == (
        "between 16:00 and 17:00 local time (CEST)"
    )
    assert local_time.in_local_time("00:30-01:30 UTC", _CHANGE_DAY) == (
        "02:30 local time (CEST)-02:30 local time (CET)"
    )


def test_a_link_or_code_span_in_the_message_passes_through_byte_for_byte() -> None:
    """A URL or a quoted field is a value someone copies, not prose."""
    link = "see https://x/?t=13:01:00Z at 14:12 UTC"
    assert local_time.in_local_time(link, _SUMMER) == (
        "see https://x/?t=13:01:00Z at 16:12 local time (CEST)"
    )
    code = "the rule fired: `startsAt: 2026-10-24T13:01:00Z`"
    assert local_time.in_local_time(code, _SUMMER) == code


def test_a_dated_stamp_from_another_day_keeps_its_date() -> None:
    """The whats_changed stamp of 15 October, read on a winter morning."""
    assert local_time.in_local_time("2026-10-14T18:08:50Z 7a7a7a7a7a", _WINTER) == (
        "14 Oct 20:08:50 local time (CEST) 7a7a7a7a7a"
    )


def test_a_time_the_model_already_converted_is_said_once() -> None:
    """Its own UTC echo in brackets collapses into the local time it wrote."""
    assert (
        local_time.in_local_time("since 16:12 local time (CEST) (14:12 UTC)", _SUMMER)
        == "since 16:12 local time (CEST)"
    )
    assert (
        local_time.in_local_time("since 16:12 local time (CEST) (14:12:00 UTC)", _SUMMER)
        == "since 16:12 local time (CEST)"
    )
    assert local_time.in_local_time("since 16:12 CEST (14:12 UTC)", _SUMMER) == (
        "since 16:12 CEST"
    )
    # A bracket naming a different moment is a second fact, not an echo.
    assert local_time.in_local_time("since 16:12 CEST (14:40 UTC)", _SUMMER) == (
        "since 16:12 CEST (16:40 local time (CEST))"
    )


def test_a_time_naming_no_zone_or_another_offset_is_left_alone() -> None:
    """Nothing may guess the clock a bare time was read off."""
    text = "at 14:12, release 1.14:12Z, and 14:12 UTC+2"
    assert local_time.in_local_time(text, _SUMMER) == text


def test_the_send_seam_rewrites_a_person_page_and_passes_a_machine_page_through(
    monkeypatch,
) -> None:
    """What `shared.signal.send` hands the transport, for each kind of send."""
    reached: list[tuple[str, str]] = []

    def transport(subject: str, body: str, *, recipient: str | None = None) -> bool:
        reached.append((subject, body))
        return True

    monkeypatch.setattr(signal, "_send_signal_raw", transport)
    stamp = "2026-10-26T13:56:00Z"
    assert signal.send("", f"down since {stamp}")
    assert signal.send("[RAW] ScoreDown", f"startsAt {stamp}")
    person, machine = reached
    assert person[0] == "" and "14:56:00 local time (CET)" in person[1]
    assert stamp not in person[1]
    assert machine == ("[RAW] ScoreDown", f"startsAt {stamp}")
