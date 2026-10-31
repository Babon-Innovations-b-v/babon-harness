"""FastAPI app, the only entrypoint the outside world hits.

Routes:
    GET  /health                  liveness; deadman probe + ingress check
    POST /webhook/alertmanager    AM v4 webhook + shared-secret header
    POST /webhook/notify          notify funnel into the notify pen:
                                  pings are QUEUED in the notify pen; the
                                  in-container flusher summarises each batch into
                                  one Signal message or silence.
    POST /webhook/heartbeat       push liveness: a heartbeat-kind
                                  registry component (a scheduled job / VM
                                  timer openclaw can't reach) proves it ran
                                  by POSTing {"component"}; records last_ok_at.
    POST /webhook/notulen         file a corrected set of minutes on the
                                  board (the notulen dashboard's button)
    POST /webhook/patrol          one patrol pass over the open worklist
                                  (timer: harness-assistant-patrol)
    POST /webhook/meeting-reminders  call reminders shortly before a meeting
                                  (timer: harness-assistant-meeting-reminders)
    POST /webhook/compact         weekly memory compact
                                  (timer: harness-assistant-weekly-compact)
    POST /webhook/claim-audit     the week's sent messages checked against the
                                  readings recorded beside them.
                                  Returns the report and SENDS NOTHING; a
                                  VM-side timer posts it to Nextcloud Talk
    GET  /relay/sent              what the assistant sent from outside the gateway's
                                  chat session, past a cursor. Read
                                  only; the VM's chat relay copies it in
    POST /mcp                     the MCP tool door: the assistant's read-only
                                  investigation tools served to a second agent
                                  over streamable-http, behind the same bearer.
                                  Built in `gates/mcp.py`; an exact Route, and
                                  it only works when this app is run with its
                                  lifespan (uvicorn does; a bare TestClient
                                  does not, and gets a 503 that says so)

Every Signal send here is followed by `outbound.remember_sent` so the
chat brain knows what it sent (outbound is memory).

Inbound Signal chat does not come through here: the OpenClaw gateway
(`assistant-gateway`) reads the Signal account itself and reaches the
assistant's tools through `POST /mcp`.

Future:
    POST /webhook/sentry          stub for a later slice

The route handlers are `_`-prefixed: the HTTP routes registered on
`app` are the interface, `app` is the file's one public object (same
shape as the notulen entrypoints exemplar). Shape-in only: no decision
logic, no DB writes besides the audit row.

FAILURE POLICY: fail-closed at the edge, Tier-1 inside. Bad shared
secret → 401; malformed payload → 400 (`ValueError`, raised either by
the JSON body read or by the parse adapters; both sit inside the same
guard, so a body that is not JSON at all is a 400 like any other bad
shape, never a 500). Triage itself never raises (Tier-2, see `core.triage`);
Signal dispatch never raises (Tier-2 dead-letter, see
`shared.signal`); the `record_alert` audit write is Tier-1, its
failure propagates as a 500 so Alertmanager retries the webhook.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from starlette.routing import Route

from apps.assistant.core import claim_audit as openclaw_claim_audit
from apps.assistant.core import compact as openclaw_compact
from apps.assistant.core import issue_sweep as openclaw_issue_sweep
from apps.assistant.core import meeting_reminders as openclaw_meeting_reminders
# The PACKAGE, not its `file_minutes` attribute. Every deep-module file in
# there is named after its one public callable and the seam re-exports that
# callable, so `from ...core.notulen import file_minutes` hands back the
# function and `.file_minutes` on it is an AttributeError at request time.
from apps.assistant.core import notulen as openclaw_notulen
from apps.assistant.core import page_hold as openclaw_page_hold
from apps.assistant.core import patrol as openclaw_patrol
from apps.assistant.core import recurring_alerts as openclaw_recurring
from apps.assistant.core import sent_feed as openclaw_sent_feed
from apps.assistant.core import outbound as openclaw_outbound
from apps.assistant.core import signal_text as openclaw_signal_text
from apps.assistant.core import state as openclaw_state
from apps.assistant.core.triage import Alert, TriageResult, triage_envelope
from apps.assistant.gates import alertmanager as alertmanager_gate
from apps.assistant.gates import heartbeat as heartbeat_gate
from apps.assistant.gates import mcp as mcp_gate
from apps.assistant.gates import notify as notify_gate
from apps.assistant.shared import auth, local_time, signal as signal_dispatch

log = logging.getLogger("openclaw")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# The MCP tool door. Built here rather than imported as a module-level
# object of its own, because a door is single-use: its lifespan starts a session
# manager that mcp 1.29.0 refuses to start twice.
_mcp_door = mcp_gate.assistant_mcp_door()

app = FastAPI(title="Openclaw", lifespan=_mcp_door.lifespan)

# An exact `Route`, never `app.mount("/mcp", ...)`. A Mount answers a POST to
# `/mcp` with a 307 to `/mcp/`, and a redirected POST can arrive without its
# body, which would look like a hung gateway rather than an error.
#
# `methods=["POST"]` is not decoration. A Route whose endpoint is an ASGI
# instance takes `methods=None` by default, which matches EVERY method, and a
# GET reaches the library's standalone-stream branch: it answers 200
# `text/event-stream` and holds the connection open for as long as the client
# keeps it. That connection would sit on the Caddy hop and the k8s-tunnel
# port-forward that the alertmanager POST also takes, which is the one thing
# `json_response=True` in `gates/mcp.py` is there to avoid. Naming the method
# turns a GET into a 405 in Starlette, before the door is entered at all. It
# also makes the route visible to the e2e suite's `registered_routes()`, which
# skips a route with no methods, so the bearer sweep now covers this door.
app.router.routes.append(
    Route("/mcp", endpoint=_mcp_door.asgi_app, name="mcp", methods=["POST"])
)

_started_at = time.time()


# The commit this image was built from, stamped in by the Dockerfile. "unknown"
# on an image built by hand, which is itself worth seeing.
_BUILD_SHA = os.environ.get("OPENCLAW_BUILD_SHA", "unknown")

# How far back the claim audit looks. A week, matching the timer that asks for
# it, so two Mondays that both fire on time cover every message once. The window
# is rolling and not bookmarked, so a tick that runs late leaves a gap rather
# than an overlap: the timer carries `Persistent=true`, and a run recovered
# after a VM reboot audits the seven days before IT ran, not the seven days it
# was supposed to. A bookmark would close that, and it would also make the
# report's headline depend on state; today the gap is a known under-count on a
# report nothing acts on automatically.
CLAIM_AUDIT_DAYS = 7


@app.get("/health")
def _health() -> dict[str, Any]:
    """Liveness, plus WHICH BUILD this is.

    With only ok and uptime, nothing in the system could tell a running pod
    apart from the commit it is supposed to be running. Both the k8s probes and
    the deadman hit this route, so "healthy" would be as far as anyone could
    see, and a container could sit behind main while every deploy cycle
    reported success. `deploy_status` cannot contradict that either: it answers
    from rows auto-deploy wrote about its own deploys.
    """
    return {
        "ok": True,
        "uptime_s": int(time.time() - _started_at),
        "build_sha": _BUILD_SHA,
    }


def _require_auth(authorization: str | None, route: str) -> None:
    """Bearer check + attacker-alerting hook. A wrong bearer is a
    401 AND a recorded `bad_bearer` security event: a burst of these is
    someone brute-forcing the shared secret, which the security sweep
    pages on. The record is DEFENDED (Tier-2 here), a failed security
    write must never turn a clean 401 into a 500 or open the gate."""
    if auth.verify(authorization):
        return
    try:
        openclaw_state.record_security_event(
            "bad_bearer", source=route, detail="401 on bearer-gated route"
        )
    except Exception as exc:  # noqa: BLE001, never let logging change the deny
        log.warning("security-event record failed (bad_bearer): %s", exc)
    raise HTTPException(status_code=401, detail="bad shared secret")


@app.post("/webhook/alertmanager")
async def _webhook_alertmanager(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Auth + shape the AM POST, fan out per-alert handling, summarise."""
    _require_auth(authorization, "/webhook/alertmanager")
    # The body read belongs INSIDE the guard: an unparseable body raises
    # JSONDecodeError (a ValueError subclass) here, one line before the parse
    # adapter is ever reached. Outside the guard that would surface as a 500,
    # so Alertmanager would retry a payload that can never parse, forever, and
    # the alert inside it would page nobody. Same shape on all four body routes.
    try:
        payload = await request.json()
        alerts = alertmanager_gate.parse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for alert in alerts:
        _record_arrival(alert)

    # Triage is a blocking LLM loop, run off the event loop so a slow triage
    # never starves /health. One decision per cause, not per alert.
    outcomes: list[TriageResult] = await asyncio.get_running_loop().run_in_executor(
        None, triage_envelope, alerts
    )

    # ONE send per envelope, not one per alert. A send inside the loop above
    # would turn a 5-alert envelope into 5 pages, and on the degrade path, where
    # the model is never consulted, into 5 identical-looking [RAW] pages.
    # Alertmanager's inhibit rules cannot help there because the
    # fan-out happens on our side, after triage.
    queued = await asyncio.get_running_loop().run_in_executor(
        None, _dispatch_batch, list(zip(alerts, outcomes))
    )

    # Audit AFTER the dispatch, so the row records what actually happened rather
    # than what we intended. Tier-1: a failed write
    # propagates and 500s the webhook so Alertmanager retries.
    #
    # QUEUED IS NOT DELIVERED, and the row says so. This road
    # hands its draft to `core/page_hold`, which may hold it until 07:30, so the
    # honest `signal_sent` here is False and the delivery stamp is written by the
    # release pass when the page really lands. What the two words must never do
    # is collapse: a queued page recorded as delivered would tell triage's
    # silence floor that a person has heard about this fingerprint when nobody
    # has, and a queued page recorded as a dead letter would page about a
    # delivery failure that has not happened.
    for alert, result in zip(alerts, outcomes):
        _record_alert(alert, result, was_queued=queued.get(alert.fingerprint, False))

    return {
        "received": len(alerts),
        "decisions": [outcome.decision for outcome in outcomes],
        "signal_queued": [queued.get(alert.fingerprint, False) for alert in alerts],
    }


def _record_arrival(alert: Alert) -> None:
    """Keep the alert itself, not only what we decided about it.

    THE HOLE THIS FILLS. The replay walks a
    recorded night back through the current gates and prints the messages that
    would leave. Without this record it cannot project many
    arrivals at all, most of them on this road, because the `alerts` table stores
    one row per DECISION and the labels and annotations triage reads are in no
    column. So the instrument could bound how NOISY a night was and not what
    the loudest road would have SAID, which is the one question the effort
    exists to answer.

    Written at intake, before triage runs, so a pass that crashes still leaves
    the payload behind. Nothing backfills: this starts the recording from the
    day it ships, and a replay of an older night keeps answering "cannot say",
    which is the honest answer rather than a reconstruction.

    Tier-2. The audit row below is Tier-1 because Alertmanager must retry a
    lost decision; a lost RECORDING costs a future replay one arrival and must
    never turn a deliverable page into a 500 and a retry storm.
    """
    try:
        openclaw_state.message_evidence.record_input(
            "alertmanager",
            alert.fingerprint,
            {
                "status": alert.status,
                "labels": alert.labels,
                "annotations": alert.annotations,
                "starts_at": alert.starts_at,
                "ends_at": alert.ends_at,
                "source": alert.source,
            },
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: a recording never costs a page
        log.warning("alert arrival record failed (swallowed): %s", exc)


def _record_alert(
    alert: Alert, result: TriageResult, *, was_queued: bool
) -> None:
    """Write the audit row for one alert, after its dispatch has been attempted.

    The audit write is Tier-1: its failure propagates and 500s the webhook so
    Alertmanager retries.

    `signal_sent` stays False on this road now. The draft was queued, not sent,
    and `core/page_hold` writes the delivered row when the page actually leaves.
    A dead letter is therefore a draft that could not even be QUEUED, which is a
    state write failing rather than Signal being unreachable, and it is still
    worth the same alarm: a page nothing is holding is a page nobody will get.
    """
    dead_letter = (
        result.signal_draft is not None
        and result.decision != "silent"
        and not was_queued
    )
    openclaw_state.record_alert(
        fingerprint=alert.fingerprint,
        name=alert.name,
        severity=alert.severity,
        status=alert.status,
        decision=result.decision,
        reason=result.reason,
        signal_sent=False,
        dead_letter=dead_letter,
    )
    log.info(
        json.dumps(
            {
                "event": "alert",
                "fingerprint": alert.fingerprint,
                "name": alert.name,
                "severity": alert.severity,
                "status": alert.status,
                "decision": result.decision,
                "reason": result.reason,
                "signal_queued": was_queued,
                "dead_letter": dead_letter,
            }
        )
    )


@app.post("/webhook/notify")
async def _webhook_notify(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Notify funnel, collect-think-summarise: the ping goes in
    the pen; the in-container flusher (`core.notify_flush`) periodically turns
    the accumulated batch into ONE summarised Signal message (or
    silence). Nothing pages per ping anymore, a crash-looping unit is
    one evolving story, not a page per failure. The enqueue is Tier-1: a
    failed write 500s this POST so the caller's direct-send fallback
    fires and the ping is never lost in a broken pen."""
    _require_auth(authorization, "/webhook/notify")
    try:
        payload = await request.json()
        notification = notify_gate.parse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    openclaw_state.enqueue_ping(
        notification.subject,
        notification.body,
        notification.source,
        notification.facts,
    )
    log.info(
        json.dumps(
            {
                "event": "notify_queued",
                "source": notification.source,
                "subject": notification.subject,
                # The keys, never the values. This is the only place a sender's
                # own marking is visible next to the ping it arrived with, and
                # a key nobody downstream reads is the shape a sender's typo
                # takes; the values can carry a redacted scan finding and have
                # no business in a log line.
                "marked": sorted(notification.facts or ()),
            }
        )
    )
    return {"queued": True}


@app.post("/webhook/heartbeat")
async def _webhook_heartbeat(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Push liveness for a `heartbeat`-kind component. A scheduled
    job / VM timer openclaw can't actively reach POSTs its component name
    here to stamp `last_ok_at`; the sweep reads that timestamp and flips
    the component down when it goes overdue. Bearer-gated, shape-in only;
    the record write is Tier-1 (a failed write 500s so the caller retries
    rather than silently losing the proof-of-life)."""
    _require_auth(authorization, "/webhook/heartbeat")
    try:
        payload = await request.json()
        beat = heartbeat_gate.parse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    openclaw_state.component_status.record_heartbeat(beat.component)
    log.info(json.dumps({"event": "heartbeat", "component": beat.component}))
    return {"recorded": beat.component}


@app.post("/webhook/notulen")
async def _webhook_notulen(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """File a corrected set of minutes on the board.

    The notulen dashboard POSTs here when somebody presses "send to the assistant".
    That button is the team's approval, so nothing here asks again: the assistant
    reads the meeting, chooses where each item belongs among the issues that
    are actually open, and writes.

    The dashboard holds the one-shot claim, not this route, because the claim
    has to survive a reply that never arrives. What this route owes the caller
    is an honest list of what it opened, and a Signal line saying the same, so
    a send that timed out on the dashboard still reaches a person.

    Bearer-gated. Tier-2 throughout: a meeting it cannot file comes back with
    the reason rather than a 500, because the minutes are safe either way and
    the person is waiting on a button."""
    _require_auth(authorization, "/webhook/notulen")
    payload = await request.json()
    missing = [
        key for key in ("job_id", "title", "meeting_date", "markdown")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing: {', '.join(missing)}")

    filed = openclaw_notulen.file_minutes(
        str(payload["job_id"]),
        str(payload["title"]),
        str(payload["meeting_date"]),
        str(payload["markdown"]),
        str(payload.get("minutes_url") or ""),
    )
    # Written on the clock the reader reads, before it is sent and remembered,
    # so the chat's copy is the text the owner saw.
    report = local_time.in_local_time(filed.as_report(str(payload["title"])))
    delivered = _send_beat(report)
    if delivered:
        openclaw_outbound.remember_sent("", report, loop="minutes")
    log.info(json.dumps({
        "event": "notulen_filed",
        "job_id": str(payload["job_id"]),
        "issues": filed.issues,
        "root": filed.root,
        "updated": filed.updated,
        "comments": filed.comments,
        "problems": len(filed.problems),
        "delivered": delivered,
    }))
    return {
        "issues": filed.issues,
        "root": filed.root,
        # Told apart from `issues` on purpose: the dashboard greys its button
        # out showing what it opened, and an action point the board already
        # carried was not opened by this press.
        "updated": filed.updated,
        "comments": filed.comments,
        "problems": filed.problems,
    }


@app.post("/webhook/patrol")
def _webhook_patrol(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run one patrol pass . The `harness-assistant-patrol` timer
    POSTs here a few times a day; the assistant works its open worklist and takes one
    look around for slow-burn trouble, then sends AT MOST one line (an update,
    an observation, or a question) or stays quiet. Bearer-gated; no payload.
    Advisory (Tier-2): a brain/budget outage returns quiet, never 500s."""
    _require_auth(authorization, "/webhook/patrol")
    # Deterministic hygiene first: adopt any loose issue under the
    # backlog PRD and ping its creator, then the judgement-driven
    # patrol pass. Tier-2 inside; a sweep fault returns [] and never blocks
    # the pass.
    adopted = openclaw_issue_sweep.sweep_orphan_issues()
    # The recurring-alerts filing lives here and not on the morning route,
    # because the morning route has no timer of its own. This pass has a timer, and `file_recurring_observations` skips a subject it has
    # already filed, so firing it three times a day files nothing twice. The
    # line is HELD rather than sent: in the morning window it leaves with the
    # night's pages, and later in the day it rides with whatever goes next.
    filed = openclaw_recurring.file_recurring_observations()
    if filed:
        openclaw_page_hold.hold_beat(openclaw_recurring.announce(filed))
    line = openclaw_patrol.patrol()
    if line is None:
        log.info(json.dumps({"event": "patrol", "sent": False, "adopted": adopted}))
        return {"sent": False, "adopted": adopted}
    text = local_time.in_local_time(line.text)
    delivered = _send_beat(text)
    if delivered:
        openclaw_outbound.remember_sent(
            "", text, loop="patrol", worklist_items=line.worklist_items
        )
    log.info(json.dumps({
        "event": "patrol", "sent": True, "delivered": delivered,
        "adopted": adopted,
    }))
    return {"sent": True, "delivered": delivered, "adopted": adopted}


@app.post("/webhook/meeting-reminders")
def _webhook_meeting_reminders(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Send the due 15-min-before video-call reminders. The
    `harness-assistant-meeting-reminders` timer POSTs here every few minutes; the assistant
    scans the near window on each teammate's calendars and Signals whoever
    has a video meeting starting soon with the call link, exactly once
    (dedup in `state.meeting_reminders`). Deterministic scan-and-send, no
    LLM. Bearer-gated; no payload. Tier-2: a fetch/send fault skips that
    item, never 500s the timer. Returns how many reminders went out."""
    _require_auth(authorization, "/webhook/meeting-reminders")
    sent = openclaw_meeting_reminders.send_due_reminders()
    log.info(json.dumps({"event": "meeting_reminders", "sent": sent}))
    return {"sent": sent}


@app.get("/relay/sent")
def _relay_sent(
    after: int = 0,
    limit: int = 20,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """The sends the gateway's chat session never saw, past `after`, oldest
    first. The VM-side chat relay keeps the cursor and copies each one
    into that session. Bearer-gated, reads only; `core.sent_feed` decides which
    roads count. A failed read is a 500, so the relay keeps its cursor."""
    _require_auth(authorization, "/relay/sent")
    feed = openclaw_sent_feed.sends_after(after, limit)
    return {"newest_id": feed.newest_id, "sends": feed.sends}


@app.post("/webhook/compact")
def _webhook_compact(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run the weekly memory compact. The
    `harness-assistant-weekly-compact` timer POSTs here; the past week's raw memory
    is folded into one durable summary. Nothing is sent to Signal. A
    skipped week (empty window, budget, brain outage) is deferred to the
    next run, never lost.

    This route is also where `message_evidence` is swept, because it is the
    only weekly clock openclaw has. The sweep runs BEFORE the compact and
    outside it: `compact_week` returns early on a fresh window, an empty
    window and a tripped budget, so a sweep placed inside it would stop
    running in exactly the quiet weeks where nothing else would notice. The
    readings table is the largest thing the assistant writes per message, and a
    retention rule nothing calls is no retention rule."""
    _require_auth(authorization, "/webhook/compact")
    swept = _sweep_readings()
    summary = openclaw_compact.compact_week()
    log.info(
        json.dumps(
            {"event": "compact", "stored": summary is not None, "readings_swept": swept}
        )
    )
    return {"compacted": summary is not None, "readings_swept": swept}


def _sweep_readings() -> int:
    """Drop readings past their retention window; never fail the compact.

    Tier-2 on purpose. Losing a week's compact because a DELETE failed would
    trade the durable memory for the disposable evidence, which is the wrong
    way round.
    """
    try:
        return openclaw_state.message_evidence.vacuum_old(
            days=openclaw_state.message_evidence.RETENTION_DAYS
        )
    except Exception:
        log.exception("message_evidence sweep failed; the compact runs anyway")
        return 0


@app.post("/webhook/claim-audit")
def _webhook_claim_audit(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """The week's sent messages, checked against the readings recorded beside
    them, returned as a report. NOTHING IS SENT FROM HERE.

    Every guard in `core/claims.py` runs on a draft and may nudge; this runs the
    same rules on what actually went out and may only report. A report about
    The assistant saying too much must not itself be a message on the phone, so the
    route hands the text back and a VM-side timer
    (`apps/assistant/watch/claim_audit/`) posts it to Nextcloud
    Talk. `notify.post_talk` needs NC_ALERTS_USER, NC_ALERTS_PASSWORD and
    NC_ALERTS_ROOM; the compose file passes them in from the vault, so the
    container CAN post to Talk, and this split stands on the ground of where
    the timer already lives. Moving
    it in is a separate change and wants its own reason.

    IT ALSO COUNTS WHAT THE ASSISTANT DID NOT SAY, because the audit
    is the only weekly clock this system has and a second route with a second
    timer and a second Talk post would be five new files to answer half a
    question. `road_shares` is the share of sent messages carrying their
    readings, per road, and it is deliberately NOT one number: the roads that
    write no delivery row are counted in `uncounted_roads` and named in the
    report with the sentence saying why, and `messages_sent` is the exact
    road-blind total from `chat_turns` that the split does not add up to.
    `unheard` is subjects nothing was ever delivered about, `held` is what is
    waiting on purpose behind the quiet-hours and pacing brakes, and those two
    are separate because a held page is the largest silence the assistant produces and
    the one that is correct.

    Bearer-gated; no payload. Tier-1 on the read, deliberately: an audit that
    answers "nothing to report" for a window it could not open is the one wrong
    answer nobody questions, so a broken read is a 500 and a visibly failed
    timer rather than a clean-looking week. That applies to all three reads: a
    silence count of zero from a table that would not open is the same wrong
    answer wearing a different hat.
    """
    _require_auth(authorization, "/webhook/claim-audit")
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=CLAIM_AUDIT_DAYS)
    judged = openclaw_claim_audit.judged_between(since.isoformat(), until.isoformat())
    findings = sum(len(one.findings) for one in judged)
    coverage = openclaw_claim_audit.coverage.between(
        since.isoformat(), until.isoformat()
    )
    silence = openclaw_claim_audit.silence.between(
        since.isoformat(), until.isoformat()
    )
    log.info(
        json.dumps(
            {
                "event": "claim_audit",
                "messages": len(judged),
                "findings": findings,
                "unheard": len(silence.unheard),
                "unheard_critical": len(silence.unheard_critical),
                "held": silence.held,
            }
        )
    )
    return {
        "messages": len(judged),
        "findings": findings,
        # Two numbers per road and never one, and the roads that cannot be
        # counted travel with the sentence saying why. See
        # `claim_audit/coverage.py`: a share computed only over the roads that
        # keep good records is a higher number over a smaller population.
        "road_shares": {
            share.road: share.share
            for share in coverage.shares
            if share.share is not None
        },
        "messages_sent": coverage.messages_sent,
        "uncounted_roads": len(coverage.unseen),
        # A silence count that counts DECISIONS THE POD MADE, never arrivals at
        # Alertmanager: a null receiver, an inhibit rule, an operator silence, a
        # group_wait fold, a refused bearer and a malformed body all leave zero
        # rows, so a night the webhook was broken answers here as a quiet night
        # and this field will say so confidently.
        "subjects": silence.subjects,
        "unheard": len(silence.unheard),
        "unheard_critical": len(silence.unheard_critical),
        "held": silence.held,
        "report": openclaw_claim_audit.render.report(
            judged, since.isoformat(), until.isoformat(), coverage, silence
        ),
    }


def _send_beat(body: str) -> bool:
    """Put one autonomous beat's message on the phone inside the Signal cap.

    `core.limits.SIGNAL_MAX_CHARS` is the declared cap on ONE Signal message,
    and every other producer applied it: triage truncates its draft, chat
    splits into follow-ups, the alertmanager batch stops packing in
    `page_hold._packed`. A beat that applied nothing could put a note of over
    two thousand characters on a phone in a single message, so the advisor and
    patrol beats overflow the way chat does, because a beat
    is the same flowing colleague prose and truncating it would drop the ask
    at the end of the note.

    Every piece is attempted even after one fails: a piece that dead-letters
    is already logged and retried by `shared.signal.send`, and stopping there
    would leave the reader with a fragment and no tail. Returns True only when
    all of them landed, so a partial delivery is never remembered as sent.
    """
    pieces = openclaw_signal_text.split_for_signal(body)
    results = [signal_dispatch.send(subject="", body=piece) for piece in pieces]
    if len(pieces) > 1:
        log.info(json.dumps({"event": "beat_split", "pieces": len(pieces)}))
    delivered = all(results)
    # Say whether it ARRIVED, not that it was handed off. This route answers
    # HTTP 200 with `delivered: false` in the body and the trigger exits 0, so
    # a beat that reached nobody looked identical to one that did, at every
    # layer above.
    openclaw_outbound.record_delivery("beat", body[:60], delivered)
    return delivered


def _dispatch_batch(pairs: list[tuple[Alert, TriageResult]]) -> dict[str, bool]:
    """Queue one page per alert the envelope has words for.

    Returns fingerprint -> queued, so each alert's audit row records what
    actually happened to it. Still one MESSAGE per envelope, and per night: the
    rows are packed by `page_hold.release`, which is where the envelope stopped
    being the unit of a message.

    ONE ROW PER ALERT, CARRYING THAT ALERT'S OWN DRAFT. Joining every draft
    in the envelope into one body and writing that whole body once per
    fingerprint would not fold: `page_hold._newest_per_key` folds only WITHIN
    a key, so N distinct fingerprints keep all N rows and `_packed` joins them
    back together with no dedup, putting the same page on the phone N times
    over, or one copy per release pass once they no longer fit under the
    Signal cap.

    Two things dissolved with the join. There is no trimming here any more, so
    no draft can be queued and audited on the strength of a message that does
    not contain it; what does not fit rides the next release pass
    (`page_hold._packed`). And the batch-level `[RAW] a, b, c` header, with the
    name dedup behind it, is gone with the batch it headed. The one-voice rule
    is unaffected and the machine marker is not lost: `triage._fallback_draft`
    writes "[RAW] " on the front of the draft itself, so a raw paragraph still
    announces that nothing checked it and the assistant's own words still carry no
    banner. Re-adding one here would print the marker twice and the alertname
    twice, which is the exact page this rule exists to prevent.
    """
    queued: dict[str, bool] = {}
    for alert, result in pairs:
        if result.decision == "silent" or result.signal_draft is None:
            continue
        _hold_page(
            result.signal_draft,
            alert=alert,
            covers=result.covers,
            worklist_items=result.worklist_items,
        )
        queued[alert.fingerprint] = True
    return queued


def _hold_page(
    body: str,
    *,
    alert: Alert,
    covers: tuple[str, ...] = (),
    worklist_items: tuple[int, ...] = (),
) -> None:
    """Queue one finished draft behind the shared brake instead of sending it.

    This is a merge, and it is a change of WIRE and not of
    voice: triage still runs its tool loop, still decides silent or not, and
    still writes the words. What it does not do is choose the moment: a draft
    sent the instant triage had it would reach a phone at any hour, including
    the quiet hours between 22:00 and 07:30.

    One row per alert, keyed by fingerprint and holding that alert's own text,
    so the row's key and the row's words mean the same thing: the release pass
    keeps the newest row per key, a fingerprint that keeps firing folds to one
    paragraph rather than seven, and the delivery stamp each key gets when the
    page lands is a stamp on words that really left. `covers` are the other
    fingerprints of the same cause, stamped delivered with the key.
    `worklist_items` are the items the page is about, which ride with it to
    the chat relay.
    """
    openclaw_state.hold_page(
        body,
        road="alertmanager",
        subject=alert.name,
        severity=alert.severity,
        key=alert.fingerprint,
        covers=",".join(covers),
        worklist_items=",".join(str(item_id) for item_id in worklist_items),
    )


