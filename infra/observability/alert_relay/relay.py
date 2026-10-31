"""relay_payload: the relay's decision, pure apart from its injected collaborators.

Alertmanager posts every alert group here. Normally the relay hands the group
to the assistant unchanged (`forward`), and the assistant triages it and
decides what reaches the phone. While the assistant deadman flag is fresh, the
assistant is verified down, and the relay becomes the road to the phone
itself: one plain message per group (`fan_out`, which the app pins to
signal-cli direct), with each alert's summary and first action, deduplicated
for half an hour per (fingerprint, status).

FAILURE POLICY: Tier 1 loud. A forward or a send that raises propagates to the
transport, which answers 500, and Alertmanager retries. Nothing here swallows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from infra.observability.alert_relay.assistant_gate import assistant_is_down
from infra.observability.alert_relay.deduper import Deduper


@dataclass(frozen=True)
class Alert:
    """One Alertmanager alert, parsed into the fields the relay needs."""
    fingerprint: str
    alertname: str
    severity: str
    status: str  # "firing" or "resolved"
    summary: str  # rendered annotation (carries the magnitude)
    first_action: str  # rendered annotation, one short line
    runbook_url: str
    instance_label: str  # best-available identifier label
    started_at: str


def _label(alert: dict) -> str:
    """The most useful identifier label: `name` for containers, `unit` for
    systemd, `mountpoint` for disks, then the catch-all `instance`."""
    labels = alert.get("labels") or {}
    for key in ("name", "unit", "mountpoint", "instance"):
        val = labels.get(key)
        if val:
            return str(val)
    return ""


def _parse_one(alert: dict) -> Alert | None:
    fingerprint = (alert.get("fingerprint") or "").strip()
    if not fingerprint:
        return None
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    return Alert(
        fingerprint=fingerprint,
        alertname=str(labels.get("alertname") or "Alert"),
        severity=str(labels.get("severity") or ""),
        status=str(alert.get("status") or ""),
        summary=str(annotations.get("summary") or annotations.get("description") or ""),
        first_action=str(annotations.get("first_action") or ""),
        runbook_url=str(annotations.get("runbook_url") or ""),
        instance_label=_label(alert),
        started_at=str(alert.get("startsAt") or ""),
    )


def _parse_payload(payload: dict) -> list[Alert]:
    """Split an Alertmanager v2 webhook payload into per-alert records.

    Payload shape: `{"version": "4", "groupKey": "...", "alerts": [...]}`.
    Drops anything missing a fingerprint (Alertmanager v2 always sets
    one; a missing field is a malformed payload).
    """
    out: list[Alert] = []
    for raw in (payload.get("alerts") or []):
        alert = _parse_one(raw)
        if alert is not None:
            out.append(alert)
    return out


def _status_word(status: str) -> str:
    return {"firing": "FIRING", "resolved": "RESOLVED"}.get(status, status.upper() or "UNKNOWN")


def _group_subject(alerts: list[Alert]) -> str:
    """First line of the message: status, alert name, severity, and a count
    when the group holds more than one alert."""
    if not alerts:
        return ""
    alertname = alerts[0].alertname
    severity = alerts[0].severity
    sev_tag = f" [{severity}]" if severity else ""
    statuses = {a.status for a in alerts}
    if len(alerts) == 1:
        return f"{_status_word(alerts[0].status)} {alertname}{sev_tag}"
    if statuses == {"firing"}:
        return f"FIRING {alertname}{sev_tag}: {len(alerts)} firing"
    if statuses == {"resolved"}:
        return f"RESOLVED {alertname}{sev_tag}: {len(alerts)} resolved"
    firing = sum(1 for a in alerts if a.status == "firing")
    resolved = sum(1 for a in alerts if a.status == "resolved")
    return f"MIXED {alertname}{sev_tag}: {firing} firing, {resolved} resolved"


def _group_body(alerts: list[Alert]) -> str:
    """One block per alert (summary with its magnitude, then the first action),
    and the group's runbook links once at the bottom."""
    if not alerts:
        return "(no alerts)"

    lines: list[str] = []
    for alert in alerts:
        block: list[str] = []
        # Status icon only when mixed-state groups need it
        prefix = ""
        statuses = {a.status for a in alerts}
        if len(statuses) > 1:
            prefix = f"{_status_word(alert.status)} "
        if alert.instance_label and alert.instance_label not in (alert.summary or ""):
            block.append(f"{prefix}{alert.instance_label}: {alert.summary}")
        else:
            block.append(f"{prefix}{alert.summary}" if alert.summary else f"{prefix}(no summary)")
        if alert.first_action:
            block.append(f"  do: {alert.first_action}")
        lines.append("\n".join(block))

    # Shared runbook URL (collapse duplicates across alerts in the group)
    runbooks = sorted({a.runbook_url for a in alerts if a.runbook_url})
    if runbooks:
        lines.append("")
        for url in runbooks:
            lines.append(f"runbook: {url}")

    # Start time for a single-alert group
    if len(alerts) == 1 and alerts[0].started_at:
        lines.append(f"started: {alerts[0].started_at}")

    return "\n".join(lines)


@dataclass(frozen=True)
class RelayOutcome:
    fingerprint: str
    #: "assistant" (handed over), "signal" (sent raw), or "deduped" (held).
    route: str


def relay_payload(
    payload: dict,
    *,
    forward: Callable[[dict], None],
    fan_out: Callable[[str, str], dict[str, bool]],
    deduper: Deduper,
    now: float | None = None,
    assistant_down: Callable[..., bool] = assistant_is_down,
) -> list[RelayOutcome]:
    """Route one Alertmanager payload. Every fingerprint comes back once.

    - Assistant up: `forward(payload)` once for the whole group.
    - Assistant down: alerts the deduper lets through go out as ONE message;
      the rest are recorded as held.
    """
    alerts = _parse_payload(payload)
    if not alerts:
        return []
    if not assistant_down(now=now):
        forward(payload)
        return [RelayOutcome(alert.fingerprint, "assistant") for alert in alerts]

    fresh = [a for a in alerts if deduper.should_send(a.fingerprint, a.status, now=now)]
    fresh_ids = {a.fingerprint for a in fresh}
    if fresh:
        fan_out(_group_subject(fresh), _group_body(fresh))
    return [
        RelayOutcome(alert.fingerprint, "signal" if alert.fingerprint in fresh_ids else "deduped")
        for alert in alerts
    ]
