"""Ask the container for the week's claim audit and bring the report back.

Its own HTTP call rather than `watch.trigger.trigger`, and that is not
duplication: `trigger` returns None and reads 200 characters of the response
body for a log line, so nothing it fires can hand anything back. Every timer
that only needs a pass fired should keep using it. This one needs the answer.

The retry ladder is copied from `trigger` deliberately, because it is about the
same wire: the container is reached over the k8s tunnel-forward, which is briefly a
zombie right after a container restart and answers 502 until auto-deploy recycles it. A
401 is a configuration error and retrying it only makes noise.

FAILURE POLICY: Tier-1 fail-loud. A report that could not be fetched must not
become an empty report, because an audit answering "nothing to report" for a
window it never read is the one wrong answer nobody questions.
"""
from __future__ import annotations

from apps.assistant.watch.door import door_url

import json
import logging
import socket
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError

log = logging.getLogger("openclaw.claim_audit.fetch")

BASE_URL = door_url()
ROUTE = "/webhook/claim-audit"
SECRET_ENV = "OPENCLAW_WEBHOOK_SECRET"

# A window read plus one pass of pure-text rules over a week of messages. No
# model call, so this is short next to the beat triggers next door.
TIMEOUT_S = 120

MAX_ATTEMPTS = 4
RETRY_BACKOFF_S = 40
RETRYABLE_STATUS = (502, 503, 504)


@dataclass(frozen=True)
class Audit:
    """What the container answered: the counts and the text a person reads.

    The four fields after `report` arrived later and all carry
    defaults, because this side of the wire outlives the container it asks: a VM timer
    fired against an older image gets a body without them, and the right answer
    to that is the report it did send rather than a crash. A default is not a
    measurement, so `metrics.render` labels them for what they are.
    """

    messages: int
    findings: int
    report: str
    road_shares: Mapping[str, float] = field(default_factory=dict)
    uncounted_roads: int = 0
    unheard: int = 0
    unheard_critical: int = 0
    held: int = 0


def fetch(secret: str) -> Audit:
    """POST the route and return the parsed audit, or raise saying why not."""
    if not secret:
        raise RuntimeError(f"{SECRET_ENV} unset, cannot ask for the claim audit")
    request = urllib.request.Request(
        f"{BASE_URL}{ROUTE}",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {secret}"},
    )
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return _parsed(response.read().decode())
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise RuntimeError(f"{ROUTE} answered HTTP {exc.code}: {exc}") from exc
            last_error = f"HTTP {exc.code}"
        except (TimeoutError, socket.timeout) as exc:
            last_error = f"timeout after {TIMEOUT_S}s"
            log.warning("%s timed out on attempt %d: %s", ROUTE, attempt, exc)
        except URLError as exc:
            last_error = str(exc.reason)
        if attempt < MAX_ATTEMPTS:
            log.warning(
                "%s attempt %d failed (%s); retrying", ROUTE, attempt, last_error
            )
            time.sleep(RETRY_BACKOFF_S)
    raise RuntimeError(f"{ROUTE} unreachable after {MAX_ATTEMPTS} attempts: {last_error}")


def _parsed(body: str) -> Audit:
    """One response body as an `Audit`, refusing a shape it does not recognise.

    A body that parses but carries no `report` key would render as an empty
    Talk post, which reads exactly like a clean week.
    """
    payload = json.loads(body)
    if not isinstance(payload, dict) or "report" not in payload:
        raise RuntimeError(f"{ROUTE} answered a shape with no report in it: {body[:200]}")
    shares = payload.get("road_shares") or {}
    return Audit(
        messages=int(payload.get("messages", 0)),
        findings=int(payload.get("findings", 0)),
        report=str(payload["report"]),
        road_shares=(
            {str(road): float(share) for road, share in shares.items()}
            if isinstance(shares, dict)
            else {}
        ),
        uncounted_roads=int(payload.get("uncounted_roads", 0)),
        unheard=int(payload.get("unheard", 0)),
        unheard_critical=int(payload.get("unheard_critical", 0)),
        held=int(payload.get("held", 0)),
    )
