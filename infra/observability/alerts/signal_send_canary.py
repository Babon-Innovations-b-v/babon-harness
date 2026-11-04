"""Prove the bot can still SEND on Signal, not just that its container runs.

signal-cli can answer receives while every send dies (a full disk stops it
unpacking its native library, for one), and then every page in the kit dies
with it. Every 30 minutes this sends one message from the bot number to
itself, which costs nobody a notification, and on success writes
`harness_signal_send_last_success_timestamp_seconds` to the textfile
directory, or to the Pushgateway as job `signal_send` in the cluster.

On success it also beats the assistant's `signal-send` heartbeat, the one
component in `apps/assistant/core/monitor/registry.py` that only this canary
can prove alive; when that beat stops, the assistant's sweep flips it down.

When the send fails there is no phone to tell: Signal is the thing under test.
The failure goes to the journal and the exit code (the failure handler knows
not to page this unit over Signal), and the outage is remembered. The first
send that works afterwards tells you once, over Signal, when sending stopped
and how many runs failed.

FAILURE POLICY: the send is Tier 1 by exit code and never retried inside a run.
The recovery message, the heartbeat and the metric write are best-effort.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from infra.observability.alerts.deadman import state_dir
from infra.observability.alerts.notify import fan_out
from infra.observability.node_textfile.textfile import publish

METRIC = "harness_signal_send_last_success_timestamp_seconds"


def _outage_file():
    return state_dir() / "send-canary-outage.json"


def _send_to_self(number: str) -> None:
    """One message from the bot to its own number. Raises on any failure."""
    base_url = os.environ.get("SIGNAL_CLI_URL", "http://127.0.0.1:8080").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/v2/send",
        data=json.dumps({"message": "canary: send path alive", "number": number, "recipients": [number]}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def _outage_so_far() -> dict | None:
    try:
        record = json.loads(_outage_file().read_text())
    except (OSError, ValueError):
        return None
    if isinstance(record, dict) and isinstance(record.get("failed_runs"), int) and record.get("since"):
        return record
    return None


def _record_failed_run(now: datetime) -> None:
    outage = _outage_so_far() or {"since": now.isoformat(timespec="seconds"), "failed_runs": 0}
    outage["failed_runs"] += 1
    try:
        _outage_file().parent.mkdir(parents=True, exist_ok=True)
        _outage_file().write_text(json.dumps(outage))
    except OSError as exc:
        print(f"could not record the failed run: {exc}", file=sys.stderr)


def _tell_it_is_back(now: datetime) -> None:
    """Say once what Signal could not carry; keep the record until a road took it."""
    outage = _outage_so_far()
    if outage is None:
        return
    since = datetime.fromisoformat(outage["since"]).strftime("%d %b %H:%M UTC")
    sent = fan_out(
        "Signal could not send, and can again",
        f"Signal sends failed from {since} until {now:%d %b %H:%M UTC}, "
        f"{outage['failed_runs']} canary run(s) in a row. Pages raised in that "
        "window did not reach you; check the alerts and the journal for that span.",
        signal_direct=True,
    )
    if sent.get("signal"):
        _outage_file().unlink(missing_ok=True)


def _beat_signal_send() -> None:
    """Tell the assistant the send path is alive. Skipped when no door secret is set."""
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
    if not secret:
        return
    from apps.assistant.watch.heartbeat import post_heartbeat

    if not post_heartbeat("signal-send", secret):
        print("send ok; could not beat the signal-send heartbeat", file=sys.stderr)


def main() -> int:
    number = os.environ.get("SIGNAL_BOT_NUMBER", "").strip()
    if not number:
        print("SIGNAL_BOT_NUMBER unset: cannot test the send path", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    try:
        _send_to_self(number)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _record_failed_run(now)
        print(f"send canary FAILED: {exc}", file=sys.stderr)
        return 1
    try:
        publish("signal_send", [
            f"# HELP {METRIC} Last time the bot sent a Signal message to itself.",
            f"# TYPE {METRIC} gauge",
            f"{METRIC} {int(time.time())}",
        ])
    except OSError as exc:
        print(f"send ok; could not write the metric: {exc}", file=sys.stderr)
    _beat_signal_send()
    _tell_it_is_back(now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
