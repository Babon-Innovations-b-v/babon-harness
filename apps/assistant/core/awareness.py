"""The current-picture block, live local state for a prompt, no tool
calls.

`render()` returns a small text block built entirely from openclaw's own
SQLite: the local time in local, the stack-liveness summary and the
newest alert-audit rows, silences excluded and a failing delivery road
folded to one line (`state.recent_alert_events`: a row saying a road
stayed quiet is bookkeeping, and this block is prompt input for every
loop). Chat pastes it into every message's system
prompt (so openclaw answers with situational awareness instead of a tool
round-trip) and the morning line builds its one-liner from it.

Single public callable: `render()`.

FAILURE POLICY: Tier-2, each read is defended; a fault degrades to a
smaller block (the time line always renders), never an error. The state
writes behind it are Tier-1 in `core.state`.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apps.assistant.core import state
from apps.assistant.core.state.alerts import NOT_AN_ARRIVAL

log = logging.getLogger("openclaw.awareness")

_MAX_ALERT_ROWS = 8


def _fingerprint_tag(row: dict) -> str:
    """The bracketed fingerprint for a row about something that arrived, and
    nothing for the assistant's own bookkeeping rows, whose prefixed fingerprint names
    a kind rather than an identity.

    Without it, two alerts of one rule on different units print as the same
    line, and triage can cite one's delivery as the other's.

    WHOLE, not a prefix: these rows are the only place triage can read another
    alert's fingerprint, and `covered_by_fingerprint` is checked by an exact
    match, so a shortened one could never name the covering page."""
    fingerprint = str(row.get("fingerprint") or "")
    if not fingerprint or fingerprint.startswith(NOT_AN_ARRIVAL):
        return ""
    return f" [{fingerprint}]"


#: The decisions that are an intent to page, which the arrival row keeps while
#: the page itself is held, sent, or dropped somewhere else.
_PAGE_DECISIONS = frozenset({"enrich", "page-raw", "page"})


def _page_outcome(row: dict) -> str:
    """What became of the page an arrival row decided on, or "" when the row
    decided no page.

    The row says "-> enrich" for ever, and a model reads that as "paged",
    so a silence can cite a page that page_hold dropped unsent."""
    if str(row.get("decision") or "") not in _PAGE_DECISIONS or row.get("signal_sent_at"):
        return ""
    held = state.held_for_arrival(str(row.get("fingerprint") or ""), str(row["received_at"]))
    if held is None:
        return " (not delivered)"
    if held.get("dropped_because"):
        return f" (dropped, never sent: {held['dropped_because']})"
    if held.get("released_at"):
        return f" (sent at {str(held['released_at'])[:16]}Z)"
    return " (held, not sent yet)"

# The silence vocabulary lives in `core/state/alerts.py` and is re-exported
# here for the readers that already name it. A prompt renderer is the wrong
# home for a storage grammar, and the file named after the table is where the
# next reader looks. Living there also lets it be a SQL clause instead of a
# Python filter, so no over-read is needed to survive one.
SILENCE_DECISIONS = state.SILENCE_DECISIONS
records_a_silence = state.records_a_silence


# Past this, the sweep has stopped rather than being between passes.
_STALE_AFTER_S = 15 * 60


def _stale_note(components: list) -> str:
    """A clause naming the age of the stack reading, or "" when it is fresh."""
    stamps = [str(row.get("last_checked_at") or "") for row in components]
    newest = max((stamp for stamp in stamps if stamp), default="")
    if not newest:
        return " (age of this reading unknown)"
    try:
        seen = datetime.fromisoformat(newest)
    except ValueError:
        return " (age of this reading unknown)"
    age = (datetime.now(timezone.utc) - seen).total_seconds()
    if age <= _STALE_AFTER_S:
        return ""
    return (
        f", WARNING: last checked {newest}, {int(age // 60)} minutes ago; the "
        "sweep has stopped, so this is stale and must not be reported as current"
    )


def render() -> str:
    """Local time + stack summary + newest alert-audit rows, as one plain
    text block."""
    now_local = datetime.now(LOCAL_ZONE)
    today = now_local.date()
    # Resolved calendar so scheduling never depends on date arithmetic in the
    # model, which gets "tomorrow" and "next Monday" wrong. The model looks a
    # weekday/relative word UP here instead of counting.
    day_labels = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        tag = " (today)" if offset == 0 else " (tomorrow)" if offset == 1 else ""
        day_labels.append(f"{day:%a} {day:%Y-%m-%d}{tag}")
    monday = today - timedelta(days=today.weekday())  # Monday of this week
    this_week = (monday, monday + timedelta(days=6))
    next_week = (monday + timedelta(days=7), monday + timedelta(days=13))
    lines = [
        f"Now: {now_local.strftime('%A %d %b %Y, %H:%M')} (local time)",
        "Dates (local time), use these exact dates, do NOT count days yourself:",
        "  " + "; ".join(day_labels),
        f"  'this week' = {this_week[0]:%Y-%m-%d}..{this_week[1]:%Y-%m-%d}; "
        f"'next week' = {next_week[0]:%Y-%m-%d}..{next_week[1]:%Y-%m-%d} (weeks run Monday to Sunday).",
        "Map any weekday, today, tomorrow, this week or next week to the exact date above.",
    ]
    try:
        components = state.component_status.get_all()
        if components:
            # No up-ratio: "Stack 36/36" is green telemetry, and a report that
            # pastes it starts narrating health it never checked. Only
            # what is DOWN is worth a line; the rest is one flat phrase.
            down = [row["component"] for row in components if row["status"] == "down"]
            unchecked = [
                row["component"]
                for row in components
                if row["status"] not in ("up", "down")
            ]
            summary = "Stack: " + (
                "DOWN: " + ", ".join(sorted(down)) if down else "nothing down"
            )
            if unchecked:
                summary += "; not checked: " + ", ".join(sorted(unchecked))
            # How old the reading is, when it is old. This block goes into EVERY
            # loop's prompt; without an age, a sweep thread that had stopped
            # would leave the assistant describing whatever was true when it
            # died. The
            # nothing-down phrase is exactly the one that must never outlive its
            # reading.
            stale = _stale_note(components)
            if stale:
                summary += stale
            lines.append(summary)
    except Exception as exc:  # noqa: BLE001, Tier-2: awareness must not break its caller
        log.warning("awareness stack read failed: %s", exc)
    try:
        recent = state.recent_alert_events(_MAX_ALERT_ROWS)
        if recent:
            lines.append("Latest alert-audit rows (newest first):")
            for row in recent:
                line = (
                    f"[{row['received_at'][:16]}Z] {row['name']}"
                    f"{_fingerprint_tag(row)} -> {row['decision']}"
                    f"{_page_outcome(row)}"
                )
                folded = int(row.get(state.FOLDED_REPEATS) or 0)
                if folded:
                    # Said once with its size rather than eight times. A failing
                    # send road retries every 30 seconds and would otherwise be
                    # the whole window inside four minutes.
                    line += f" (and {folded} more like it in this window)"
                lines.append(line)
    except Exception as exc:  # noqa: BLE001, Tier-2: awareness must not break its caller
        log.warning("awareness alerts read failed: %s", exc)
    picture = "THE CURRENT PICTURE, live state from your own records:\n" + "\n".join(
        lines
    )
    # Which tools are actually usable belongs in the current picture, not in a
    # separate block only chat sees: every loop pastes awareness, so
    # declaring the gaps here reaches triage, patrol, morning and evening too.
    # Empty when everything is ready, so it costs nothing on a healthy pod.
    try:
        from apps.assistant.core import tools

        gaps = tools.readiness_block()
        if gaps:
            picture += "\n\n" + gaps
    except Exception as exc:  # noqa: BLE001, Tier-2: awareness must not break its caller
        log.warning("awareness readiness read failed: %s", exc)
    return picture
