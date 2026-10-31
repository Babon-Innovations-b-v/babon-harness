"""Scaleway status enrichment: say when an outage is probably theirs, not yours.

Wraps the raw-message `fan_out`: when status.scaleway.com lists an open
critical or major incident touching the region the kit runs in (SCW_REGION,
default fr-par) or a shared service it uses, one line is appended to the
message. Alerts keep their severity; enrichment never suppresses anything.

FAILURE POLICY: fail-open. Any fetch error or schema surprise returns the body
unchanged and logs one warning; delivery never waits on Scaleway's status page.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

SCALEWAY_STATUS_URL = "https://status.scaleway.com/api/v2/incidents/unresolved.json"
CACHE_TTL_S = 60.0
HTTP_TIMEOUT_S = 5.0

# Shared services whose open incidents likely affect the stack. Names match
# `components[].name` on status.scaleway.com verbatim; Scaleway has used both
# Kubernetes names, so both are carried.
_SHARED_COMPONENTS = frozenset({
    "Object Storage",
    "Container",
    "Serverless Containers",
    "Kubernetes",
    "Kubernetes Kapsule",
    "Secret Manager",
    "Databases",
    "Managed Database for PostgreSQL and MySQL",
    "APIs",
})


def watched_components() -> frozenset[str]:
    """The region's zones plus the shared services."""
    region = os.environ.get("SCW_REGION", "").strip() or "fr-par"
    return _SHARED_COMPONENTS | {f"{region}-{zone}" for zone in (1, 2, 3)}


WATCHED_IMPACTS = frozenset({"critical", "major"})
WATCHED_STATUSES = frozenset({"investigating", "identified", "monitoring"})


def _default_fetch() -> dict:
    """Network fetch, separate so tests inject a fake."""
    req = urllib.request.Request(
        SCALEWAY_STATUS_URL,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read())


@dataclass
class _Cache:
    """Per-wrapper-instance cache. Initial ts=0.0 means never fetched."""
    ts: float = 0.0
    line: str = ""


def _format_incident(incident: dict) -> str | None:
    """One incident → one line, or None if it doesn't match our watch
    list / severity / status."""
    name = (incident.get("name") or "").strip()
    impact = (incident.get("impact") or "").lower()
    status = (incident.get("status") or "").lower()
    if impact not in WATCHED_IMPACTS or status not in WATCHED_STATUSES:
        return None
    components = incident.get("components") or []
    matched = [
        c.get("name") for c in components
        if c.get("name") in watched_components()
    ]
    if not matched:
        return None
    affected = ", ".join(matched)
    started = (incident.get("created_at") or "").strip()
    started_suffix = f" (started {started})" if started else ""
    return (
        f"Upstream: Scaleway {impact} incident \"{name}\" affecting "
        f"{affected}: https://status.scaleway.com{started_suffix}"
    )


def _build_line(payload: dict) -> str:
    """All matching open incidents → newline-joined block. Empty when
    nothing matches."""
    incidents = (payload or {}).get("incidents") or []
    formatted = [
        line for line in (_format_incident(i) for i in incidents)
        if line
    ]
    return "\n".join(formatted)


def _enrich(
    body: str,
    *,
    cache: _Cache,
    fetch: Callable[[], dict] = _default_fetch,
    now: float | None = None,
    ttl_s: float = CACHE_TTL_S,
) -> str:
    """Append Scaleway-status line(s) to body when an open watched
    incident is in flight. Fail-open on any error."""
    current = time.time() if now is None else now
    if cache.ts > 0 and current - cache.ts < ttl_s:
        line = cache.line
    else:
        try:
            payload = fetch()
            line = _build_line(payload)
        except Exception as exc:  # noqa: BLE001 (deliberate fail-open)
            log.warning("scaleway-status fetch failed: %s", exc)
            line = ""
        cache.ts = current
        cache.line = line
    if not line:
        return body
    return f"{body}\n\n{line}"


def wrap_fan_out(
    fan_out: Callable[[str, str], dict[str, bool]],
    *,
    fetch: Callable[[], dict] = _default_fetch,
) -> Callable[[str, str], dict[str, bool]]:
    """Return a fan_out callable that enriches each body before sending.

    Cache is per-wrapper-instance, so the module-level call in app.py
    produces one cache per process. Concurrent requests may race on
    the cache; worst case is one extra fetch per expiry window.
    """
    cache = _Cache()

    def enriched(subject: str, body: str) -> dict[str, bool]:
        return fan_out(subject, _enrich(body, cache=cache, fetch=fetch))

    return enriched
