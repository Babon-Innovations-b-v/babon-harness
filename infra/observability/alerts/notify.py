"""The one place a page leaves the harness: Signal, through the assistant or direct.

Every alert, deadman and unit-failure page calls `fan_out` or `send_signal`.
Standard library only, so a page still goes out when a virtualenv is broken:
the systemd units run it with the system python3.

Two roads to the phone:

- The default road hands the message to the assistant's notify door
  (`{ASSISTANT_URL}/webhook/notify`, bearer OPENCLAW_WEBHOOK_SECRET), so the
  assistant can batch, triage and keep an audit row. The POST is retried, so a
  container restart during a deploy does not drop the message. When every
  attempt fails, the same text goes straight to signal-cli instead, because
  this kit has no second channel to park it in.
- The direct road posts to signal-cli's REST API (`{SIGNAL_CLI_URL}/v2/send`)
  from SIGNAL_BOT_NUMBER to SIGNAL_RECIPIENT (default: the first
  SIGNAL_ALLOWLIST entry). The deadmen always take it (`signal_direct=True`):
  a canary for the assistant being down must never report through the
  assistant.

FAILURE POLICY: best-effort. Every function returns a bool or a dict of bools
and never raises, so a broken channel cannot crash its caller. The deadman
entrypoints that call this are the loud layer.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from urllib.error import HTTPError, URLError

log = logging.getLogger(__name__)

_DEFAULT_SIGNAL_CLI_URL = "http://127.0.0.1:8080"
_DEFAULT_ATTEMPTS = 3
_DEFAULT_RETRY_S = 20.0
#: Signal itself accepts far longer messages; this keeps one page readable on a
#: phone and is where a long body is split rather than cut.
SIGNAL_PIECE_MAX_CHARS = 2000


def assistant_url() -> str:
    """Where the assistant's doors answer, as seen from this process.

    Host-side callers (the systemd units) reach it on loopback at OPENCLAW_PORT;
    the alert-relay container sets ASSISTANT_URL to the compose service name.
    """
    explicit = os.environ.get("ASSISTANT_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("OPENCLAW_PORT", "").strip() or "8000"
    return f"http://127.0.0.1:{port}"


def signal_recipient() -> str:
    """SIGNAL_RECIPIENT, or the first SIGNAL_ALLOWLIST entry, or ""."""
    explicit = os.environ.get("SIGNAL_RECIPIENT", "").strip()
    if explicit:
        return explicit
    for entry in os.environ.get("SIGNAL_ALLOWLIST", "").split(","):
        if entry.strip():
            return entry.strip()
    return ""


def compose_signal_pieces(subject: str, body: str) -> list[str]:
    """The text the phone reads, split at whitespace into Signal-sized pieces.

    An empty subject sends the bare body. Split, never truncated: in a page the
    thing to do is usually the last line.
    """
    text = f"{subject}\n\n{body}" if subject else body
    pieces: list[str] = []
    remaining = text
    while len(remaining) > SIGNAL_PIECE_MAX_CHARS:
        cut = remaining.rfind("\n", 0, SIGNAL_PIECE_MAX_CHARS)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, SIGNAL_PIECE_MAX_CHARS)
        if cut <= 0:
            cut = SIGNAL_PIECE_MAX_CHARS
        pieces.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining or not pieces:
        pieces.append(remaining)
    return pieces


def send_signal(
    subject: str,
    body: str,
    *,
    direct: bool = False,
    facts: dict | None = None,
) -> bool:
    """Send one message to the owner's phone. True when a road took it.

    `direct=True`, or no OPENCLAW_WEBHOOK_SECRET configured, sends through
    signal-cli. Otherwise the assistant's notify door is tried
    NOTIFY_GATEWAY_ATTEMPTS times, NOTIFY_GATEWAY_RETRY_S apart, and the
    message goes direct if it never answers.

    `facts` is what the sender knows as fields (an exit code, an error line, a
    command to run). It rides to the assistant; the direct road drops it.
    """
    if direct or not os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip():
        return _send_signal_cli(subject, body)
    try:
        attempts = max(1, int(os.environ.get("NOTIFY_GATEWAY_ATTEMPTS", _DEFAULT_ATTEMPTS)))
        retry_gap = float(os.environ.get("NOTIFY_GATEWAY_RETRY_S", _DEFAULT_RETRY_S))
    except ValueError:
        attempts, retry_gap = _DEFAULT_ATTEMPTS, _DEFAULT_RETRY_S
    for attempt in range(1, attempts + 1):
        if _send_via_assistant(subject, body, facts):
            return True
        if attempt < attempts:
            time.sleep(retry_gap)
    log.warning("assistant notify door unreachable for %r; sending direct", subject)
    return _send_signal_cli(subject, body)


def _send_via_assistant(subject: str, body: str, facts: dict | None) -> bool:
    """POST to the assistant's notify door. True on 2xx."""
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
    notification: dict = {"subject": subject, "body": body, "source": "notify"}
    if facts:
        notification["facts"] = facts
    request = urllib.request.Request(
        f"{assistant_url()}/webhook/notify",
        data=json.dumps(notification).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
        return True
    except HTTPError as exc:
        log.error("assistant notify door failed: HTTP %d", exc.code)
        return False
    except (URLError, OSError) as exc:
        log.error("assistant notify door failed: %s", exc)
        return False


def _send_signal_cli(subject: str, body: str) -> bool:
    """POST every piece to signal-cli `/v2/send`. True only if all landed."""
    bot_number = os.environ.get("SIGNAL_BOT_NUMBER", "").strip()
    recipient = signal_recipient()
    if not (bot_number and recipient):
        log.warning("signal-cli not configured (SIGNAL_BOT_NUMBER/SIGNAL_RECIPIENT); skipping")
        return False
    base_url = os.environ.get("SIGNAL_CLI_URL", _DEFAULT_SIGNAL_CLI_URL).rstrip("/")
    for piece in compose_signal_pieces(subject, body):
        payload = json.dumps(
            {"number": bot_number, "recipients": [recipient], "message": piece}
        ).encode()
        request = urllib.request.Request(
            f"{base_url}/v2/send",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except HTTPError as exc:
            log.error("signal-cli send failed: HTTP %d", exc.code)
            return False
        except (URLError, OSError) as exc:
            log.error("signal-cli send failed: %s", exc)
            return False
    return True


def fan_out(
    subject: str,
    body: str,
    *,
    signal_direct: bool = False,
    facts: dict | None = None,
) -> dict[str, bool]:
    """Send a page and log one receipt line saying whether it got through.

    Returns `{"signal": bool}`; a dict so a caller can treat every channel the
    same way if a second one is ever added. Never raises.
    """
    result = {"signal": send_signal(subject, body, direct=signal_direct, facts=facts)}
    if result["signal"]:
        log.info("page delivered: %s", subject[:120])
    else:
        log.error("PAGE NOT DELIVERED: %s", subject[:120])
    return result
