"""Attacker-alerting sweep, turn recorded security events into a page. Runs on the notify-flush cadence; edge-triggered so a sustained
attack pages when it crosses a threshold, not every tick.

Two signals, both on openclaw's own surface (`gates.app`
`record_security_event`):

- ``bad_bearer``: a 401 on a bearer-gated ``/webhook/*`` route. A BURST
  is someone brute-forcing the shared secret, page at
  ``_BAD_BEARER_BURST`` in ``_BAD_BEARER_WINDOW_MIN`` minutes.
- ``unauthorized_chat``: a chat attempt from a non-allowlisted Signal
  number, someone found the bot number. High-signal and rare, so page
  on the FIRST one in the window.

The page is SENT DIRECTLY (not through the notify pen): the pen runs
every batch through an LLM noise filter, and a security page must never
be silenceable as "noise", which a body saying "refused, nothing got in"
would invite. The
edge-trigger below already prevents spam (one page per burst until the
window empties), so it needs no pen pacing. It is still recorded as
outbound memory so the assistant knows it warned you.

Single public callable: ``sweep_security()``.

FAILURE POLICY: Tier-2, a read/send fault is logged and the sweep
returns; a broken security sweep must never take the flusher down.
"""
from __future__ import annotations

import logging

from apps.assistant.core import outbound as _outbound
from apps.assistant.core import security_judge as _judge
from apps.assistant.core import state
from apps.assistant.shared import local_time as _local_time
from apps.assistant.shared import signal as _signal

log = logging.getLogger("openclaw.security_sweep")

_BAD_BEARER_WINDOW_MIN = 10
_UNAUTH_WINDOW_MIN = 15
# Noise floor: below this, don't even wake the judgement (a stray 401 or one
# fat-fingered chat isn't worth a thought). This is NOT the page threshold:
# it only decides when there's ENOUGH activity to be worth REASONING about.
# The page decision itself is the judgement, not a count.
_CONSIDER_BAD_BEARER = 8
_CONSIDER_UNAUTH = 1

# Rate backstop only (PERSISTED, survives restarts): run the (LLM) judgement
# at most once per cooldown per concern, so a sustained condition doesn't
# re-reason every 30s tick or re-fire after a pod restart. NOT the decision:
# whether to page inside that window is still the judgement's call.
_JUDGE_COOLDOWN_S = 1800


def sweep_security() -> str | None:
    """Hand notable security activity to the JUDGEMENT (security_judge), which
    reasons about whether it's real/new/worth interrupting and may check the
    recent deploys before deciding. Returns the sent message, or None. The
    counts here are only a floor for 'worth thinking about' and a rate
    backstop, the page decision is reasoned, not a threshold."""
    try:
        bad = state.count_since("bad_bearer", _BAD_BEARER_WINDOW_MIN)
        unauth = state.count_since("unauthorized_chat", _UNAUTH_WINDOW_MIN)
    except Exception as exc:  # noqa: BLE001, Tier-2: never kill the flusher
        log.warning("security sweep read failed: %s", exc)
        return None

    # When activity clears, re-arm so a genuinely fresh burst is reconsidered
    # at once rather than waiting out the backstop.
    if bad < _CONSIDER_BAD_BEARER and unauth < _CONSIDER_UNAUTH:
        state.clear_page_cooldown("sec:judge")
        return None

    # Enough activity to be worth a thought; but only spend the judgement
    # (an LLM pass) once per backstop window.
    if not state.should_page("sec:judge", _JUDGE_COOLDOWN_S):
        return None

    senders = sorted({
        event["source"]
        for event in state.recent_security_events(_UNAUTH_WINDOW_MIN)
        if event["kind"] == "unauthorized_chat"
    })
    try:
        body = _judge.judge_security(bad, unauth, senders)
    except Exception as exc:  # noqa: BLE001, Tier-2: never kill the flusher
        log.warning("security judgement failed: %s", exc)
        return None
    if not body:
        return None  # the judgement decided it wasn't worth interrupting
    body = _local_time.in_local_time(body)
    try:
        if _signal.send(subject="", body=body):
            _outbound.remember_sent("security", body, loop="security")
    except Exception as exc:  # noqa: BLE001, Tier-2: never kill the flusher
        log.warning("security page send failed: %s", exc)
        return None
    return body
