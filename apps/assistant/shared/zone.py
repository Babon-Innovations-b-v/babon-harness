"""The owner's local time zone, read once from ASSISTANT_TIMEZONE.

Every clock time a person reads (pages, briefs, calendar answers, quiet
hours) is written on this zone. Unset means UTC, which is never wrong, only
unfriendly; the owner sets an IANA name such as Europe/Berlin.
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

LOCAL_ZONE_NAME: str = os.environ.get("ASSISTANT_TIMEZONE", "").strip() or "UTC"
LOCAL_ZONE: ZoneInfo = ZoneInfo(LOCAL_ZONE_NAME)

__all__ = ["LOCAL_ZONE", "LOCAL_ZONE_NAME"]
