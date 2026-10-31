"""Report a road that is still sending and has stopped recording.

WHY THIS WATCH EXISTS. Every claim an issue makes about a live week has the
shape "the audit would find that", and the audit's denominator is the recording
itself: `outbound.remember_readings` writes one `message_evidence` row per
released message, and a checker reads those rows. So a road that keeps sending
and quietly stops recording does not make the audit worse, it makes it look
CLEANER, because the messages that could have failed a check are the ones that
are missing. It is the same failure shape as an alarm that cannot fire, and it
multiplies over every other number in the effort.

It is made worse by design, and the design is right. `remember_readings`
swallows its own write faults on purpose: the message has already gone out, and
failing the caller then would cost a real message to save a record of it. A
broken recorder therefore looks exactly like a quiet week from every angle
except this one.

The only watch that existed before this one is
`apps/assistant/watch/claim_audit/watch.py`, and it fires only when the WHOLE
window is empty. One road going dark inside a window that still has the other
roads in it passes it silently.

WHAT IT COMPARES. Deliveries against recordings, per road, in one window. The
join is the trap `core/roads.py` was written for: readings are stored under a
LOOP name (`patrol`) and deliveries are stamped with a ROAD's delivery kind
(`beat`), so anything that reads either as the other reports the wrong road as
unrecorded. The register owns both names and `countable_roads()` is the list of
roads that declare both, which is the only list a comparison like this can
honestly be made over. Roads that record nothing BY DESIGN are not in it and
are not findings; the report names them anyway, with the register's own reason,
because leaving them out would be the same flattering omission this file exists
to catch.

WHAT IT CAN GET WRONG, SAID HERE RATHER THAN FOUND LATER. The advisor sends
through the same `_send_beat` seam as patrol, so its delivery row is stamped
`beat` too and nothing in the audit table tells the two apart; that is why the
register leaves the advisor uncountable. A week in which patrol never ran and
the advisor did therefore has `beat` deliveries and no `patrol` recordings, and
this watch calls that a road that stopped recording. It is a report worth
reading either way (a beat road with no readings behind its messages is the
thing an issue measures) but the cause named in it may be the wrong one. The
honest fix is a delivery kind of the advisor's own, which is `core/outbound.py`
and not this lane.

MIND THE RETENTION WINDOW. `message_evidence` is vacuumed at `RETENTION_DAYS`
(90) from the compact route, so a window that reaches back that far loses its
far end to the vacuum and every road in it decays toward "stopped recording". A
window that long is refused rather than answered: a manufactured gap in this
report would send somebody hunting a recorder that is working. The delivery side
has the opposite bound, `alerts` is pruned by nothing, but the read is capped at
`_MAX_ROWS` newest first, which can only hide OLD deliveries and therefore can
only make this watch miss a gap, never invent one.

WHAT IT IS NOT. Not part of `run_sweep`, for the same reason `dead_letters.py`
is not: the sweep is the paging path and this is a check ON that path, so it is
its own module called from `runner.py` in its own try block, and a bug here
cannot take monitoring down with it. Not a `registry.Component` either: all six
check kinds (http, db, kubectl, heartbeat, external) target a
thing outside this pod, and what this reads is openclaw's own table.

SAYING IT ONCE. A check that repeats itself every sweep is a new noise source
inside an effort to reduce noise, so a road reported here is not reported again
until the window has passed. That memory is in this process and not in a table:
the state package has no migrations, adding a table to it is another lane's
file, and a repeat after a pod restart is a bounded cost since restarts follow
deploys rather than a clock. Same trade as the dead-letter watermark next door.

FAILURE POLICY: Tier-2. Reads and the report are defended, and an undelivered
report leaves the roads unmarked so the next pass says it again.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import logging
from datetime import datetime, timedelta, timezone

from apps.assistant.core import roads, state
from apps.assistant.core.monitor import talk

log = logging.getLogger("openclaw.monitor.unrecorded_roads")

# The window this runs over by default: the length of the live trial an issue
# is built for, so what it reports is what that week's audit would be reading.
WINDOW_DAYS = 7

# Most audit rows one window read returns, newest first. A window that produces
# more than this loses its OLDEST rows, so the effect is a delivery this watch
# cannot see and therefore a gap it fails to report; it can never invent one.
# At a handful of rows a day, a 7-day window uses well under a hundred of them.
_MAX_ROWS = 5000

# The audit fingerprint every delivery row carries (`outbound.record_delivery`).
_DELIVERY_PREFIX = "delivery:"

# When each road was last reported, so a standing gap is said once per window.
_reported: dict[str, datetime] = {}

# Roads found in a gap that no channel would take a report about.
_stranded: int = 0


def reset() -> None:
    """Test hook: forget what has been reported and what is stranded."""
    global _stranded
    _reported.clear()
    _stranded = 0


def stranded() -> int:
    """How many gapped roads no channel has accepted a report about."""
    return _stranded


def check(window_days: int = WINDOW_DAYS) -> int:
    """Report roads that delivered in the window and recorded nothing.

    Returns how many roads were FOUND in that state this pass, which is zero
    once a road has been reported and until the window has passed. `stranded()`
    answers how many of them reached nobody, the same pair of answers the
    dead-letter watch gives, for the same reason.
    """
    global _stranded
    now = datetime.now(timezone.utc)
    if not _window_is_visible(window_days):
        return 0
    since = now - timedelta(days=window_days)
    try:
        delivered = _deliveries_by_kind(since.isoformat())
        recorded = _loops_that_recorded(since.isoformat(), now.isoformat())
    except Exception as exc:  # noqa: BLE001, Tier-2: never break the runner
        log.warning("road recording read failed: %s", exc)
        return 0

    gaps = [
        road
        for road in roads.countable_roads()
        if delivered.get(road.delivery_kind, 0) > 0
        and road.loop not in recorded
        and _due(road.name, now, window_days)
    ]
    if not gaps:
        _stranded = 0
        return 0

    names = ", ".join(road.name for road in gaps)
    accepted = talk.report(
        f"🔴 [the project] {ASSISTANT_NAME} is sending on a road that records nothing",
        _body(gaps, delivered, window_days, since),
    )
    if not accepted:
        # Unmarked on purpose: a road nobody was told about has not been
        # reported, so the next pass has to say it again.
        _stranded = len(gaps)
        log.error("unrecorded road(s) reached nobody, holding: %s", names)
        talk.nobody_can_be_told("unrecorded-road watch")
        return len(gaps)

    for road in gaps:
        _reported[road.name] = now
    _stranded = 0
    log.warning("reported unrecorded road(s) via %s: %s", ", ".join(accepted), names)
    return len(gaps)


def _window_is_visible(window_days: int) -> bool:
    """Whether the whole window is still on disk to be read.

    Refusing is the honest answer to a window longer than the retention: the
    rows at its far end have been vacuumed, so every road in it would read as
    one that stopped recording, and a manufactured gap costs somebody a hunt
    for a recorder that is working.
    """
    retention = state.message_evidence.RETENTION_DAYS
    if window_days < 1:
        log.error("refusing a window of %d day(s): there is nothing in it", window_days)
        return False
    if window_days >= retention:
        log.error(
            "refusing a %d-day window: readings are vacuumed at %d days, so its "
            "far end is gone and every road in it would read as stopped",
            window_days,
            retention,
        )
        return False
    return True


def _deliveries_by_kind(since_iso: str) -> dict[str, int]:
    """How many messages each delivery kind put on the wire since `since_iso`.

    A message that failed to send counts: the road SENT, which is the half this
    watch asks about, and whether it arrived is the dead-letter watch's question
    one module along.
    """
    counted: dict[str, int] = {}
    for row in state.alerts_since(since_iso, limit=_MAX_ROWS):
        fingerprint = str(row.get("fingerprint", ""))
        if not fingerprint.startswith(_DELIVERY_PREFIX):
            continue
        kind = fingerprint[len(_DELIVERY_PREFIX):]
        counted[kind] = counted.get(kind, 0) + 1
    return counted


def _loops_that_recorded(start_iso: str, end_iso: str) -> set[str]:
    """Every loop name that stored a message with its readings in the window."""
    return {
        str(row.get("loop", ""))
        for row in state.message_evidence.said_between(start_iso, end_iso)
    }


def _due(road_name: str, now: datetime, window_days: int) -> bool:
    """Whether this road may be reported again yet."""
    last = _reported.get(road_name)
    return last is None or (now - last) >= timedelta(days=window_days)


def _body(
    gaps: list[roads.Road],
    delivered: dict[str, int],
    window_days: int,
    since: datetime,
) -> str:
    """The report: what stopped recording, and what this watch cannot see.

    The second half is not politeness. Four of the nine roads record no readings
    at all and two more write no delivery row, so a report naming only the roads
    it can compare would read as a clean bill of health over a population it
    never looked at.
    """
    countable = roads.countable_roads()
    uncomparable = [road.name for road in roads.ROADS if road not in countable]
    consequence = (
        "An audit over this window will report that road as clean, because the "
        "audit's denominator is the recording. Check "
        "`outbound.remember_readings`, which swallows its own write faults on "
        "purpose, and the loop that should be calling it."
    )
    coverage = (
        "Not compared at all, because the register says they record no readings, "
        "no deliveries, or neither: " + ", ".join(uncomparable) + "."
    )
    lines = [f"Window: the {window_days} day(s) since {since.isoformat()}.", ""]
    for road in gaps:
        lines.append(
            f"The {road.name} road delivered {delivered.get(road.delivery_kind, 0)} "
            "message(s) and recorded not one of the readings behind them "
            f"(readings are stored under the loop name {road.loop})."
        )
    lines += ["", consequence, "", coverage]
    return "\n".join(lines)
