"""list_events tool, events in a window, across one or all calendars.

Unparseable VEVENTs are skipped (Tier-2 swallow, documented at the site):
one malformed third-party event must not blank the whole listing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..ical import parse_iso, parse_vcal
from ..runtime import ensure_client


def list_events(
    calendar: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """List events in a window. Defaults: next 14 days, every visible calendar.

    Args:
        calendar: display name or url-tail. None = all calendars.
        start: ISO8601 start (inclusive). Default = now.
        end: ISO8601 end (exclusive). Default = now + 14 days.
    """
    client = ensure_client()
    window_start = parse_iso(start) if start else datetime.now(timezone.utc)
    window_end = parse_iso(end) if end else window_start + timedelta(days=14)
    targets = [client.find(calendar)] if calendar else client.calendars()
    out: list[dict] = []
    for handle in targets:
        try:
            results = handle._cal.search(start=window_start, end=window_end, event=True, expand=True)
        except Exception as exc:
            raise RuntimeError(f"calendar {handle.name!r} search failed: {exc}") from exc
        for raw in results:
            try:
                event = parse_vcal(raw.data, calendar_name=handle.name)
            except Exception:
                # Tier-2 swallow: a single malformed VEVENT (third-party
                # clients produce these) must not fail the whole listing.
                continue
            out.append(event.to_dict())
    return out
