"""Notification transport: the one place a page leaves the assistant.

Consumed by the door's own loops (through `shared/signal.py`), the gateway
watch and the claim audit. One module means one place to add a channel and
one message format everywhere. Standard library only.

FAILURE POLICY: every function here is Tier-2 best-effort: log and return
``bool`` (True on success), never raise. A broken channel must not crash the
calling request handler or mask the other channel. The deadman entrypoints
that call it are the loud layer.

Three channels:

- `post_talk()`   Nextcloud Talk via basic-auth OCS POST. Settings:
  NC_ALERTS_USER, NC_ALERTS_PASSWORD, NC_ALERTS_ROOM, NC_URL (default
  https://cloud.<DOMAIN>).
- `send_signal()` Signal, via the assistant and signal-cli. Every
  notification passes through it:
    * The default path routes through the door's notify route
      (`{OPENCLAW_NOTIFY_URL}/webhook/notify`, bearer
      OPENCLAW_WEBHOOK_SECRET), so every message goes out FROM the bot
      number and gets an audit row. The POST is retried
      (OPENCLAW_GATEWAY_ATTEMPTS, default 3, OPENCLAW_GATEWAY_RETRY_S
      apart) so a restart during a deploy does not degrade the channel.
      When every attempt fails the phone gets a rate-limited ONE-LINE
      pointer to Talk, never the raw dump: the Talk leg of `fan_out`
      already carries the full text.
    * Inside the assistant container (OPENCLAW_GATEWAY_SELF=1) it sends to
      signal-cli direct and never re-POSTs to itself.
    * A deadman switch calls `fan_out(..., signal_direct=True)` so it
      bypasses the door entirely: it is the canary for the door being
      down and must page even when the door is unreachable.
  signal-cli is called at `{SIGNAL_CLI_URL}/v2/send` (optional bearer
  SIGNAL_CLI_BEARER) with recipient = SIGNAL_RECIPIENT (default: the first
  SIGNAL_ALLOWLIST entry) and sender = SIGNAL_BOT_NUMBER.
- `send_email()`  SMTP via stdlib `smtplib`, for a box whose provider allows
  outbound SMTP. Not in `fan_out()` by default, because many cloud
  providers block outbound SMTP from their instances.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import time
import urllib.parse
import urllib.request
from pathlib import Path
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.error import HTTPError, URLError

log = logging.getLogger(__name__)


# ── Nextcloud Talk ──────────────────────────────────────────────────────────

def post_talk(message: str) -> bool:
    """POST a chat message to the configured Talk conversation.

    Returns True on 2xx, False otherwise. Truncates to 4000 chars so we
    never hit Talk's body limit.
    """
    nc_url = (os.environ.get("NC_URL") or f"https://cloud.{os.environ.get('DOMAIN', 'example.org')}").rstrip("/")
    user = os.environ.get("NC_ALERTS_USER", "")
    pwd = os.environ.get("NC_ALERTS_PASSWORD", "")
    room = os.environ.get("NC_ALERTS_ROOM", "")

    if not (user and pwd and room):
        log.warning("Talk creds not configured (NC_ALERTS_*); skipping post")
        return False

    url = f"{nc_url}/ocs/v2.php/apps/spreed/api/v1/chat/{room}"
    form = f"message={urllib.parse.quote(message[:4000])}"
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=form.encode(),
        method="POST",
        headers={
            "OCS-APIRequest": "true",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {auth}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except HTTPError as e:
        log.error("Talk post failed: HTTP %d, %s",
                  e.code, e.read().decode()[:300])
        return False
    except URLError as e:
        log.error("Talk post failed: %s", e)
        return False


# ── Email (SMTP) ────────────────────────────────────────────────────────────

def send_email(subject: str, body: str,
               recipient: str | None = None) -> bool:
    """Send a plain-text email via SMTP. Returns True on success.

    Uses stdlib `smtplib` (no Django dependency) so it works identically
    from the systemd timer script and from inside the FastAPI relay. If
    SMTP_USER / SMTP_PASSWORD aren't set, logs a warning and returns
    False, don't crash the caller.
    """
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    # The default sender is the account we authenticate as: a relay that is
    # not in the From domain's SPF fails alignment and lands in spam. Set
    # ALERT_EMAIL_FROM only when SMTP_HOST is a relay aligned for that domain.
    sender = os.environ.get("ALERT_EMAIL_FROM") or user
    # No hardcoded fallback recipient: the destination is
    # config, not code. Unset ALERT_EMAIL_TO means "email channel off".
    to = recipient or os.environ.get("ALERT_EMAIL_TO", "")

    if not to:
        log.warning("ALERT_EMAIL_TO not configured; skipping email")
        return False

    if not (host and user and pwd):
        log.warning("SMTP host or creds not configured; skipping email")
        return False

    host_name, _, port_str = host.partition(":")
    port = int(port_str or 587)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(sender.rpartition("@")[2] or None))
    msg.set_content(body)

    try:
        with smtplib.SMTP(host_name, port, timeout=10) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("SMTP send failed: %s", e)
        return False


# ── Signal ──────────────────────────────────────────────────────────────────
#
# ONE transport (CallMeBot retired): the VM-side signal-cli-rest-api
# `/v2/send`, sender = the dedicated bot number. `send_signal` is the funnel
# every alert/notification passes through; by default it routes through the
# openclaw notify gateway so every message goes out FROM the bot number and
# gets an audit row, falling back to a direct signal-cli send if the gateway
# is unreachable. The dead-man's switches call `fan_out(signal_direct=True)`
# so they bypass the gateway entirely, they are the canary for openclaw
# being down and must page even when the gateway is unreachable.

_DEFAULT_SIGNAL_CLI_URL = "http://signal-cli:8080"
_DEFAULT_OPENCLAW_NOTIFY_URL = "http://assistant:8000"
_SIGNAL_TEXT_MAX_CHARS = 4000
# Gateway retry: a deploy rolls the assistant container for a few minutes, and a
# single-attempt POST would turn each of those windows into raw pages.
_GATEWAY_ATTEMPTS_ENV = "OPENCLAW_GATEWAY_ATTEMPTS"
_DEFAULT_GATEWAY_ATTEMPTS = 3
_GATEWAY_RETRY_ENV = "OPENCLAW_GATEWAY_RETRY_S"
_DEFAULT_GATEWAY_RETRY_S = 20.0
# Fallback pointer rate limit: during an openclaw outage many callers hit the
# fallback at once; the phone gets at most one pointer per gap window.
_FALLBACK_STATE_DIR_ENV = "NOTIFY_FALLBACK_STATE_DIR"
_DEFAULT_FALLBACK_STATE_DIR = "/var/lib/harness/notify-fallback"
_FALLBACK_MIN_GAP_ENV = "NOTIFY_FALLBACK_MIN_GAP_S"
_DEFAULT_FALLBACK_MIN_GAP_S = 900.0


def _signal_recipient() -> str:
    """The real destination Signal number.

    Prefer an explicit SIGNAL_RECIPIENT; otherwise reuse the first entry of
    SIGNAL_ALLOWLIST (the owner's E.164). NEVER SIGNAL_PHONE, that env is the
    legacy CallMeBot account UUID (a 36-char handle), not a phone number,
    and signal-cli would reject it as a recipient.
    """
    explicit = os.environ.get("SIGNAL_RECIPIENT", "").strip()
    if explicit:
        return explicit
    allowlist = os.environ.get("SIGNAL_ALLOWLIST", "")
    for entry in allowlist.split(","):
        if entry.strip():
            return entry.strip()
    return ""


def send_signal(
    subject: str,
    body: str,
    *,
    direct: bool = False,
    recipient: str | None = None,
    facts: dict | None = None,
) -> bool:
    """Dispatch a Signal message. Returns True on success, False on any
    failure (so the caller's dead-letter / retry policy fires; 
    never swallow silently).

    Routing:
      - `direct=True`, OPENCLAW_GATEWAY_SELF=1 (set only inside the
        assistant container), or an explicit `recipient` → send signal-cli
        direct, never the gateway.
      - otherwise → POST to the openclaw notify gateway, retried
        (OPENCLAW_GATEWAY_ATTEMPTS × OPENCLAW_GATEWAY_RETRY_S apart) so
        a container restart is ridden out; when every attempt fails the phone
        gets a rate-limited one-line pointer to Talk instead of the raw
        text. The full text is not lost: fan_out's Talk leg
        always carries it, and the deadman canary pages "openclaw down".

    `recipient` overrides the destination (an E.164 number); default None
    keeps the pinned ops recipient. A targeted teammate message
    must never route through the notify pen, which pages the ops
    recipient, so any `recipient` forces the direct path.

    `facts` is what THIS sender knows about the thing it is paging about,
    in fields rather than in prose: the error line it pulled out,
    the command it offers, its own hedge, its exit status, and whether it
    stopped the deploy. It rides to the pen and is read there; the direct
    signal-cli paths drop it, and that is not a loss, because they are the
    paths that exist for when the pen is unreachable and there is nothing
    on the other end to read a typed field.
    """
    if direct or recipient or os.environ.get("OPENCLAW_GATEWAY_SELF", "").strip() == "1":
        return _send_signal_cli(subject, body, recipient)
    if not os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip():
        # No gateway wired in this environment, signal-cli IS the transport
        # here, so the full message goes direct (not a pointer).
        return _send_signal_cli(subject, body)
    try:
        attempts = max(1, int(os.environ.get(_GATEWAY_ATTEMPTS_ENV, _DEFAULT_GATEWAY_ATTEMPTS)))
        retry_gap = float(os.environ.get(_GATEWAY_RETRY_ENV, _DEFAULT_GATEWAY_RETRY_S))
    except ValueError:
        attempts, retry_gap = _DEFAULT_GATEWAY_ATTEMPTS, _DEFAULT_GATEWAY_RETRY_S
    for attempt in range(1, attempts + 1):
        if _send_via_gateway(subject, body, facts):
            return True
        if attempt < attempts:
            time.sleep(retry_gap)
    log.warning(
        "openclaw notify gateway unreachable for %r after %d attempts; "
        "raw text stays in Talk, sending pointer if due",
        subject, attempts,
    )
    return _send_fallback_pointer(subject)


def _send_fallback_pointer(subject: str) -> bool:
    """Gateway exhausted: the phone gets one short pointer per gap window,
    never the raw dump. The full text is already in
    Talk via fan_out's Talk leg. Rate limit is a stamp file so concurrent
    callers during an outage collapse to one pointer; fail-OPEN on state
    errors, better a duplicate pointer than a silent phone."""
    if not _fallback_pointer_due():
        log.warning("fallback pointer for %r suppressed (within gap window)", subject)
        return False
    headline = subject.strip() or "a notification"
    return _send_signal_cli(
        "⚠️ [the project] openclaw unreachable",
        f"Could not hand off: {headline}\n"
        "Full detail is in Talk; more may be parked there until openclaw is back.",
    )


def _fallback_pointer_due() -> bool:
    """True iff no fallback pointer went out within the gap window; stamps
    now on True. Fail-open: any state error sends the pointer."""
    try:
        gap = float(os.environ.get(_FALLBACK_MIN_GAP_ENV, _DEFAULT_FALLBACK_MIN_GAP_S))
        state_dir = Path(os.environ.get(_FALLBACK_STATE_DIR_ENV, _DEFAULT_FALLBACK_STATE_DIR))
        state_dir.mkdir(parents=True, exist_ok=True)
        stamp = state_dir / "last-pointer"
        now = time.time()
        if stamp.exists():
            last = float(stamp.read_text().strip() or 0)
            if now - last < gap:
                return False
        stamp.write_text(str(now))
        return True
    except Exception as exc:  # noqa: BLE001, fail-open: never silence the last channel
        log.warning("fallback pointer gate errored (%s); sending anyway", exc)
        return True


def _send_via_gateway(subject: str, body: str, facts: dict | None = None) -> bool:
    """POST the notification to the openclaw notify gateway
    (`/webhook/notify`) so it goes out from the bot number with an audit
    row. Bearer-gated with OPENCLAW_WEBHOOK_SECRET. Returns True on 2xx,
    False on any failure so `send_signal` can fall back to a direct send.

    The `facts` key is added only when this sender marked something, so a
    sender that marks nothing POSTs the payload it always POSTed. That
    matters in one direction: this file ships ahead of the container on the VM
    and inside the alert-relay image, so it can be newer than the gate it
    is talking to, and an old gate that has never heard of the key is
    handed a body it recognises whole.
    """
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("OPENCLAW_WEBHOOK_SECRET not set; cannot route via gateway")
        return False
    base_url = os.environ.get(
        "OPENCLAW_NOTIFY_URL", _DEFAULT_OPENCLAW_NOTIFY_URL
    ).rstrip("/")
    notification = {
        "subject": subject,
        "body": body,
        "source": os.environ.get("OPENCLAW_NOTIFY_SOURCE", "notify"),
    }
    if facts:
        notification["facts"] = facts
    payload = json.dumps(notification).encode()
    req = urllib.request.Request(
        f"{base_url}/webhook/notify",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except HTTPError as e:
        log.error("openclaw notify gateway failed: HTTP %d, %s",
                  e.code, e.read().decode()[:300])
        return False
    except URLError as e:
        log.error("openclaw notify gateway failed: %s", e)
        return False


def _compose_signal_text(subject: str, body: str) -> str:
    """Render the exact text the phone will show, capped at the transport max.

    An empty subject sends the bare body: openclaw's own voice has no banner
    line. Machine pages (deadman,
    raw fallbacks) keep their subject as the first line.

    Split out of `_send_signal_cli` because it was the only
    place this rule was implemented AND it lived inside the one function the
    e2e sink has to replace to keep messages off real phones. A captured run
    therefore never contained the composed string, so the rule was invisible
    to the harness and pinned nowhere else: deleting the `if subject` branch
    left every test green. Composing here keeps the sender a sender, and lets both a
    test and the sink read what would have gone out.
    """
    return f"{subject}\n\n{body}" if subject else body


def _signal_pieces(text: str) -> list[str]:
    """The message as Signal-sized pieces, split at whitespace.

    This used to be `text[:4000]` inside `_compose_signal_text`, a second and
    larger cap than the 1500 declared in `core/limits.py`, and it TRUNCATED.
    Anything reaching this sender without having been split first lost its tail,
    and in a page the tail is where the thing to do lives: the ask is at the end.
    The callers that arrive unsplit are the ones with the longest bodies,
    `fire_alert` with a thirty-line log tail among them.

    One cap now, the one in `core/limits.py`, and prose is split rather than cut.
    The import is lazy on purpose: `core.signal_text` is openclaw's, openclaw
    imports THIS module, and a top-level import would close that loop.
    """
    try:
        from apps.assistant.core.signal_text import split_for_signal
    except Exception:  # noqa: BLE001, the sender outlives a missing splitter
        return [text[:_SIGNAL_TEXT_MAX_CHARS]]
    return split_for_signal(text) or [text]


def compose_signal_pieces(subject: str, body: str) -> list[str]:
    """What the phone actually reads: the composed message, in the pieces it
    will arrive as.

    Public and outside `_send_signal_cli` on purpose. The e2e sink replaces that
    function wholesale to keep messages off real phones, so anything decided
    inside it exists in no captured run and is pinned nowhere, and a rule put
    there can be lost without any test noticing.
    """
    return _signal_pieces(_compose_signal_text(subject, body))


def _send_signal_cli(subject: str, body: str, recipient: str | None = None) -> bool:
    """Send a Signal message via the VM-side signal-cli-rest-api `/v2/send`.

    `SIGNAL_BOT_NUMBER` is the dedicated bot number signal-cli is registered
    as (the message sender, +15550100099); it is a phone number, not a
    secret. The recipient is the real destination number from
    `_signal_recipient()` (SIGNAL_RECIPIENT or the first SIGNAL_ALLOWLIST
    entry), never SIGNAL_PHONE, which is the legacy CallMeBot UUID.
    `SIGNAL_CLI_URL` points at the service (VM-local container by default,
    the bearer-gated Caddy route for cluster/serverless callers);
    `SIGNAL_CLI_BEARER` guards that route.

    Length-capped + bool contract so callers' dead-letter / retry policy is
    transport-agnostic.
    """
    bot_number = os.environ.get("SIGNAL_BOT_NUMBER", "")
    recipient = (recipient or "").strip() or _signal_recipient()
    if not (bot_number and recipient):
        log.warning(
            "signal-cli not configured (SIGNAL_BOT_NUMBER/SIGNAL_RECIPIENT"
            "/SIGNAL_ALLOWLIST); skipping"
        )
        return False

    base_url = os.environ.get("SIGNAL_CLI_URL", _DEFAULT_SIGNAL_CLI_URL).rstrip("/")
    headers = {"Content-Type": "application/json"}
    bearer = os.environ.get("SIGNAL_CLI_BEARER", "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    # Every piece has to land for this to be a delivery. A partial send is a
    # message whose ask never arrived, which reads to the recipient exactly like
    # a message that says less than it meant to.
    for piece in compose_signal_pieces(subject, body):
        payload = json.dumps({
            "number": bot_number,
            "recipients": [recipient],
            "message": piece,
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/v2/send", data=payload, method="POST", headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except HTTPError as e:
            log.error("signal-cli send failed: HTTP %d, %s",
                      e.code, e.read().decode()[:300])
            return False
        except (URLError, OSError) as e:
            log.error("signal-cli send failed: %s", e)
            return False
    return True


# ── Fan-out ─────────────────────────────────────────────────────────────────

def fan_out(
    subject: str,
    body: str,
    *,
    signal_direct: bool = False,
    signal: bool = True,
    facts: dict | None = None,
) -> dict[str, bool]:
    """Send to Nextcloud Talk + Signal serially (both are fast).

    Returns per-channel status so the caller can record it in
    ops_activity. Does NOT raise on channel failure: an alert system
    should never eat its own exceptions silently, but one channel going
    down should not mask the other working.

    `signal_direct=True` forces the Signal leg to bypass the openclaw
    notify gateway and send signal-cli direct. The dead-man's switches set
    this: they are the canary for openclaw being down, so they must never
    route through the very thing they watch.

    `signal=False` skips the Signal leg entirely (reported as False in
    the result). alert-relay's raw safety-net fan-out uses this (the rule is
    no raw alert dumps on the phone, ever): raw detail goes
    to Talk only, and Signal keeps exactly two voices, openclaw's
    triaged pages, and the deadman's "openclaw down" canary that says
    look at Talk.

    `facts` is what this sender knows about its own page, as fields
   ; it rides the Signal leg into the notify pen. The Talk leg
    ignores it, because Talk gets the whole body and a typed field is a
    thing to say something FROM, not a thing to say.

    Email is intentionally excluded from the default fan-out because many
    providers block outbound SMTP from their instances. Call `send_email()`
    directly where it is allowed.
    """
    result = {
        "talk": post_talk(f"**{subject}**\n\n{body}"),
        "signal": (
            send_signal(subject, body, direct=signal_direct, facts=facts)
            if signal
            else False
        ),
    }
    _log_delivery(subject, result, signal_requested=signal)
    return result


def _log_delivery(subject: str, result: dict[str, bool], *, signal_requested: bool) -> None:
    """Write one line saying what actually got through.

    Fifteen callers call `fan_out` and one reads what it returns, so the
    per-channel answer this function already has was being thrown away
    everywhere else. The VM deploy log is the clearest case: `fire_alert`
    writes "ALERT: <subject>" BEFORE it tries to send and nothing writes
    anything after, so the log could record pages as sent while the reader
    received none of them. The channels each log their own failure, but
    unlabelled and detached from the alert, so a bare "openclaw notify gateway
    failed: HTTP 502" reads as unrelated noise.

    One line per page, naming the subject and every channel's answer. It is a
    receipt, not an alarm: a page must never fail because reporting on it did,
    so nothing here raises and nothing here blocks.
    """
    channels = ", ".join(
        f"{name}={'ok' if ok else 'FAILED'}"
        for name, ok in result.items()
        if name != "signal" or signal_requested
    )
    if any(result.values()):
        log.info("page delivered [%s]: %s", channels, subject[:120])
    else:
        log.error("PAGE NOT DELIVERED [%s]: %s", channels, subject[:120])
