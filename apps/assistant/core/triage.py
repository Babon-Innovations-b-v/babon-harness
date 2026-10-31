"""Triage decision interface, the deep module behind `triage(alert)`.

External contract: a single `triage(alert)` entry point that returns a
`TriageResult`. Behind it: bounded Anthropic tool-use loop, hard daily
budget cap, decision tree (silent / enrich / page-raw), Signal draft.
`Alert` and `TriageResult` are the call's signature types and ride
with it.

FAILURE POLICY: Tier-2 degrade, never drop. `triage()` always returns
a `TriageResult`, every internal fault collapses to `page-raw` with a
`[RAW]`-prefixed fallback draft, so a broken brain still pages the owner.
The one swallow (`anthropic.APIError` → page-raw) is defended below at
the catch site. State reads/writes (dedup, suppression, budget) are
Tier-1 and propagate, see `core.state`.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

from apps.assistant.shared.name import ASSISTANT_NAME

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo

import anthropic

from apps.assistant.core import brain as _brain
from apps.assistant.core import claims as _claims
from apps.assistant.core import outbound as _outbound
from apps.assistant.core import self_context as _self_context
from apps.assistant.core import sent_feed as _sent_feed
from apps.assistant.core import signal_text as _signal_text
from apps.assistant.core import state as _state, tools as _tools
from apps.assistant.core.limits import (
    LLM_MAX_ITERATIONS,
    REPAGE_AFTER_HOURS,
    SIGNAL_MAX_CHARS,
)
from apps.assistant.core.state.alerts import last_delivered_at

log = logging.getLogger("openclaw.triage")

TriageDecision = Literal["silent", "enrich", "page-raw", "log-only"]


@dataclass(frozen=True)
class Alert:
    """The shape we feed `triage()` after the gate parses the AM payload.

    One Alert per AM `alerts[]` element. The webhook gate hands the
    envelope to `triage_envelope`, which makes one triage call per cause:
    per alert, except for alerts that share a scrape path.
    """

    fingerprint: str
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str
    source: Literal["alertmanager", "sentry", "manual"] = "alertmanager"

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "<unnamed>")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "info")


@dataclass(frozen=True)
class TriageResult:
    decision: TriageDecision
    reason: str
    signal_draft: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    #: The fingerprints this decision speaks for besides its own: the other
    #: alerts of one shared cause in the same envelope (`triage_envelope`).
    covers: tuple[str, ...] = ()
    #: The worklist item a page is about, as the model named it, so the chat
    #: relay can tell the chat which item a reply answers.
    worklist_items: tuple[int, ...] = ()


_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, the team's ops triage worker.

You receive one infrastructure alert at a time. Your job: decide whether to page
the on-call human (the owner), and if so, draft a Signal message they can read in 5
seconds on their phone.

Available investigation tools (read-only): `kubectl_get`, `kubectl_describe`,
`kubectl_logs`, `kubectl_events` (cluster state); `gh_issue_view`,
`gh_issue_list`, `gh_pr_view`, `gh_commits` (in-flight work + what landed);
`db_query` (SELECT-only ops Postgres: runs/ops_activity/alerts/deploys);
`loki_query`
and `prom_query` (logs + metrics). Use them sparingly, every call costs
tokens.

Decision options:
- `silent`, known noise, already paged recently, AM heartbeat ("Watchdog"),
  freshness-check flakes, or any alert with no actionable signal. No Signal
  message sent. A page about a still-firing alert that was already paged in
  the last {REPAGE_AFTER_HOURS} hours is dropped before it is sent, so there
  choose `silent`.
- `enrich`, real alert; investigate, then page with the Loki traceback
  excerpt + relevant context (pod state, recent logs, related issue) attached.
- `page-raw`, real alert but you couldn't enrich (tool failure, timeout, or
  you're just out of investigation budget). Page the owner with the bare AM payload.

Output style (when paging): terse and plain, like a quick human text. Drop
filler, lead with the thing then cause, quote error strings exact. Cap the
draft tight (one glanceable page); longer context goes into a follow-up message in a later
slice. PLAIN TEXT ONLY: Signal shows markdown literally, so no asterisks,
backticks, emoji, bullets, headings, or divider rules; short newline-separated
lines if you need a list.

State a date, time, count or check result, in a draft or a reason, only when
a tool result in this pass or the alert payload shows it; otherwise say you did
not read it.

An alert's `where_to_look_not_for_the_reader` names the evidence for it. Run
every part of it your tools can reach yourself (db_query, prom_query,
loki_query, kubectl); never quote it, and never hand the rest to the reader.
Name a unit or service only when a tool result or the alert showed it. Every
clock time in a draft is local time, never UTC: the alert's own
times are UTC, so convert them.

Finish by calling `submit_triage_decision` with your decision, reason, and the
Signal draft (or null if silent). Do this exactly once."""


#: Annotations the model is never shown as they are. `first_action` is written
#: for a person at a terminal ("ssh deploy@... 'sudo systemctl restart ...'"),
#: and a draft written around it would lose its fix step to
#: `signal_text.strip_markdown`, leaving "To un-stall it:" with nothing after
#: it on the phone. A person still reads it in Alertmanager and Grafana.
_ANNOTATIONS_NOT_FOR_THE_MODEL = frozenset({"first_action"})

#: The key `first_action` reaches the model under when it is a pointer to
#: evidence rather than a shell command: the repo-index alert's names an
#: ops_activity query db_query can run, and without it triage may invent a unit
#: and ask the owner to read its log.
_WHERE_TO_LOOK = "where_to_look_not_for_the_reader"


def _where_to_look(alert: Alert) -> str | None:
    """`first_action` when it is not a command for a terminal on the VM."""
    pointer = str(alert.annotations.get("first_action") or "").strip()
    if not pointer or "ssh " in pointer:
        return None
    return pointer


def _format_alert_for_llm(alert: Alert) -> str:
    annotations = {
        key: value
        for key, value in alert.annotations.items()
        if key not in _ANNOTATIONS_NOT_FOR_THE_MODEL
    }
    pointer = _where_to_look(alert)
    if pointer:
        annotations[_WHERE_TO_LOOK] = pointer
    return json.dumps(
        {
            "fingerprint": alert.fingerprint,
            "status": alert.status,
            "name": alert.name,
            "severity": alert.severity,
            "labels": alert.labels,
            "annotations": annotations,
            "starts_at": alert.starts_at,
            "ends_at": alert.ends_at,
            "source": alert.source,
        },
        indent=2,
    )


def _page_history_for_llm(alert: Alert) -> str:
    """The one line of page history the model is given, read by fingerprint.

    Code, not memory: the prompt rows carry no fingerprint, and a
    silence that rebuilt its history from them borrowed another alert's
    delivery time."""
    delivered = last_delivered_at(alert.fingerprint)
    if delivered:
        # The count and the local time come from code: the model never sees
        # the silent rows, so it cannot count them or convert a Z time itself.
        silenced = _state.silences_since(alert.fingerprint, delivered)
        return (
            f"Page history for fingerprint {alert.fingerprint}: last delivered "
            f"to a phone at {delivered[:16]}Z ({_local_clock(delivered)} "
            f"local time); silenced {silenced} times since by triage. Quote "
            "these two if you need them; do not count anything yourself."
        )
    return (
        f"Page history for fingerprint {alert.fingerprint}: nothing about it "
        "has ever reached a phone."
    )


def _fallback_draft(alert: Alert, prefix: str = "") -> str:
    """The page for when there is no model: deterministic, and written the way
    a person would write it.

    Not "EndpointDown (critical) [em dash] probe returning unhealthy status
    (10m)" under a subject that already reads "[RAW] EndpointDown": the name
    twice, a label where the plain answer belongs (`core.voice`: never open with a label, a header or a category),
    and the em dash soul.md rule 5 forbids. What a reader needs is what is
    wrong, then which alert said so, then that nobody has verified it.

    The "[RAW] " prefix stays, and the reason is now STRONGER than it was.
    It used to be one of two markers: the batch in `gates/app._dispatch_batch`
    went out under its own "[RAW] a, b, c" banner subject, and this prefix rode
    on each draft inside it. That banner is gone with the batch it headed, so the gate adds no
    marker of any kind and `page_hold.release` packs finished paragraphs under
    an empty subject. This prefix is therefore the ONLY thing on the wire saying
    a paragraph is a machine page nobody checked, which is exactly what a reader
    needs to know about it.
    """
    summary = str(alert.annotations.get("summary") or "").strip()
    if summary:
        body = f"{summary} ({alert.name}, {alert.severity}). I am passing this on unchecked."
    else:
        # Nothing to lead with but the name, so the name leads.
        body = (
            f"{alert.name} came in at {alert.severity} with no summary "
            f"(fingerprint {alert.fingerprint}). I am passing this on unchecked."
        )
    full = f"{prefix}{body}" if prefix else body
    return full[:SIGNAL_MAX_CHARS]


def _extract_submit(response: anthropic.types.Message) -> dict | None:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _tools.SUBMIT_NAME:
            return dict(block.input)
    return None


def _coerce_decision(raw: dict, alert: Alert) -> TriageResult:
    decision = raw.get("decision")
    reason = str(raw.get("reason") or "no-reason-given")
    signal_draft = raw.get("signal_draft")
    if decision == "silent":
        return TriageResult(decision="silent", reason=reason, signal_draft=None)
    if decision not in ("enrich", "page-raw"):
        return TriageResult(
            decision="page-raw",
            reason=f"llm-bad-decision: {decision!r}",
            signal_draft=_fallback_draft(alert, prefix="[RAW] "),
        )
    if not isinstance(signal_draft, str) or not signal_draft:
        signal_draft = _fallback_draft(alert)
    else:
        # The presentation seam every other person-facing loop already crosses
        # (patrol, chat, the brief, the pen, the advisor, the digest): markdown
        # Signal would show literally, a command written for the reader to run,
        # an em dash. An enriched page went straight to the phone without it.
        # A page may never go silent, so an emptied draft falls to the template.
        signal_draft = _signal_text.strip_markdown(signal_draft) or _fallback_draft(alert)
    return TriageResult(
        decision=decision,
        reason=reason,
        signal_draft=signal_draft[:SIGNAL_MAX_CHARS],
    )


#: The label a Prometheus scrape config may put on every target it scrapes
#: through one shared hop (a tunnel or a proxy). When that hop
#: wedges, every target behind it goes dark at once and each is its own alert,
#: which would otherwise reach the owner as many separate diagnoses that
#: contradict each other.
_SHARED_PATH_LABEL = "scrape_via"


def _cause_key(alert: Alert) -> str:
    """What one envelope's alerts are grouped by: the shared scrape path when
    the alert carries one, and its own fingerprint otherwise."""
    via = alert.labels.get(_SHARED_PATH_LABEL)
    if not via:
        return alert.fingerprint
    return "|".join((alert.status, alert.name, alert.labels.get("component", ""), via))


def _same_cause_line(siblings: list[Alert]) -> str:
    """The prompt line naming the other alerts one decision speaks for."""
    named = ", ".join(
        f"{sibling.labels.get('job', sibling.name)}/{sibling.labels.get('instance', '')} "
        f"[{sibling.fingerprint}]"
        for sibling in siblings
    )
    return (
        f"Same cause: {len(siblings)} more alerts in this envelope share this "
        f"alert's scrape path ({_SHARED_PATH_LABEL}="
        f"{siblings[0].labels.get(_SHARED_PATH_LABEL)}), and your one decision "
        f"and one draft speak for all of them: {named}. Diagnose the shared path once."
    )


def triage_envelope(alerts: list[Alert]) -> list[TriageResult]:
    """One decision per cause in an Alertmanager envelope, in the envelope's order.

    Alerts that share a scrape path are one cause, so only one of them, the
    leader, goes to the model, and the rest are recorded as silent under it.
    The leader is the lowest fingerprint and not the first in the envelope,
    because Alertmanager does not keep the order, and a leader that changed on
    every four-hourly resend would give the held page a new key each time and
    escape both the fold and the already-paged check.
    """
    buckets: dict[str, list[Alert]] = {}
    for alert in alerts:
        buckets.setdefault(_cause_key(alert), []).append(alert)
    decided: dict[str, TriageResult] = {}
    for members in buckets.values():
        leader = min(members, key=lambda member: member.fingerprint)
        siblings = [member for member in members if member is not leader]
        result = triage(leader, same_cause=siblings)
        decided[leader.fingerprint] = replace(
            result, covers=tuple(sibling.fingerprint for sibling in siblings)
        )
        for sibling in siblings:
            decided[sibling.fingerprint] = TriageResult(
                decision="silent", reason=f"same cause as {leader.fingerprint}"
            )
    return [decided[alert.fingerprint] for alert in alerts]


def triage(alert: Alert, same_cause: list[Alert] | None = None) -> TriageResult:
    suppressed, suppression_reason = _state.is_suppressed(alert.name)
    if suppressed:
        return TriageResult(
            decision="silent",
            reason=f"suppressed: {suppression_reason}",
        )

    if alert.status == "resolved":
        return _all_clear(alert, same_cause or [])

    if _state.dedup_check_and_touch(alert.fingerprint):
        return TriageResult(
            decision="silent",
            reason="dedup-window-hit",
        )

    content = _format_alert_for_llm(alert) + "\n\n" + _page_history_for_llm(alert)
    if same_cause:
        content += "\n\n" + _same_cause_line(same_cause)
    open_items = _open_items_for_llm()
    if open_items:
        content += "\n\n" + open_items
    messages: list[dict] = [{"role": "user", "content": content}]
    tool_calls_log: list[dict] = []
    # Reads that actually returned data, an UNAVAILABLE or FAILED render is
    # not evidence, so it must not count as having looked.
    reads = {"ok": 0}
    # What the reads actually SAID, not just how many there were. The guard used
    # to get a bare counter and pass anything with a count above zero, so it only
    # ever caught the read-nothing case while every diagnosis drawn out of thin
    # air AFTER a successful read sailed through. The text was
    # always in hand here and only a 200-character excerpt was kept.
    read_text: list[str] = []
    # Every reading of this pass, the alert as given first, stored beside what
    # the pass said so the weekly claim audit can check it. Otherwise they
    # die with the call, and "confirmed via curl" can never be checked.
    readings = [_outbound.Reading.of("alert", {}, "ok", content)]

    def _dispatch(name: str, tool_input: dict) -> str:
        result_text = _tools.execute(name, tool_input)
        outcome = "ok"
        if result_text.startswith(("UNAVAILABLE", "FAILED", "unknown tool")):
            outcome = result_text.split(None, 1)[0].rstrip(":").lower()
        else:
            reads["ok"] += 1
            read_text.append(result_text)
        readings.append(_outbound.Reading.of(name, tool_input, outcome, result_text))
        tool_calls_log.append(
            {"tool": name, "input": tool_input, "result_excerpt": result_text[:200]}
        )
        return result_text

    # The metered tool-use loop lives in `core.brain`; triage keeps its own
    # decision tree and degrade. The submit-tool is the loop's terminal: when
    # the model calls it the brain stops and hands the response back here. The
    # system prompt (spine + this loop's task) comes from `core.self_context`,
    # so triage now sees the current picture and the date like every loop. The
    # recent_sent block in the spine also stops it re-paging the same firing
    # alert Alertmanager re-delivers each repeat_interval.
    system = _self_context.render("triage", _SYSTEM_PROMPT)
    outcome = _brain.run(
        system=system,
        messages=messages,
        tools=_tools.TOOL_DEFINITIONS,
        cap=LLM_MAX_ITERATIONS,
        dispatch=_dispatch,
        terminal_tools=frozenset({_tools.SUBMIT_NAME}),
    )

    # Every non-`finished` outcome degrades to a raw page (Tier-2): a broken
    # brain still pages the owner. The reason distinguishes the cause.
    _RAW_REASON = {
        "budget-tripped": "budget-tripped",
        "faulted": "anthropic-fault",
        "cap-hit": "iteration-cap",
    }
    if outcome.status != "finished":
        return TriageResult(
            decision="page-raw",
            reason=_RAW_REASON[outcome.status],
            signal_draft=_fallback_draft(alert, prefix="[RAW] "),
            tool_calls=tool_calls_log,
        )

    submit_payload = _extract_submit(outcome.response)
    if submit_payload is None:
        # Model stopped on plain text without ever submitting a decision.
        return TriageResult(
            decision="page-raw",
            reason="llm-no-progress",
            signal_draft=_fallback_draft(alert, prefix="[RAW] "),
            tool_calls=tool_calls_log,
        )
    final = _coerce_decision(submit_payload, alert)
    conversation = _Conversation(
        system=system,
        messages=messages,
        dispatch=_dispatch,
        response=outcome.response,
        payload=submit_payload,
    )

    def _draft_gates(result: TriageResult) -> TriageResult:
        """The checks every draft the model writes passes before it can leave."""
        result = _causal_gate(
            result, alert=alert, conversation=conversation, reads=reads, read_text=read_text
        )
        result = _handover_gate(
            result, alert=alert, conversation=conversation, given=content, read_text=read_text
        )
        return _plumbing_gate(result, alert=alert)

    final = _draft_gates(final)
    final = _unread_stamp_gate(final, alert=alert, given=content, read_text=read_text)
    final = _page_claim_gate(
        final, alert=alert, conversation=conversation, check_draft=_draft_gates
    )
    # Last, so the two mechanical silences above have already returned and a
    # human's mute can never reach it.
    final = _silence_floor(final, alert=alert)
    _outbound.remember_readings(
        "triage", _what_was_said(final), readings, recipient=alert.fingerprint
    )
    return TriageResult(
        decision=final.decision,
        reason=final.reason,
        signal_draft=final.signal_draft,
        tool_calls=tool_calls_log,
        worklist_items=_named_item(conversation.payload) if final.signal_draft else (),
    )


def _open_items_for_llm() -> str:
    """The open worklist items a page could be about, as a block for the user turn.

    Without it the model could fill `worklist_item` only by guessing, which the
    field forbids. It is the relay's own capped list, the page recipient's items
    and the assistant's, so a long worklist cannot bury the alert. No recipient
    configured or no open item gives no block.
    """
    address = _outbound.recipient()
    items = _sent_feed.open_items_for(address) if address else []
    if not items:
        return ""
    lines = [
        "Open worklist items this page could be about. Set `worklist_item` to "
        "one of these ids only when the alert is the problem that item tracks:"
    ]
    lines.extend(f"item {item['id']}: {item['title']}" for item in items)
    return "\n".join(lines)


def _named_item(payload: dict) -> tuple[int, ...]:
    """The worklist item id the newest submit named, kept only while that item is open."""
    raw = payload.get("worklist_item")
    if isinstance(raw, bool):
        return ()
    try:
        item_id = int(raw)
    except (TypeError, ValueError):
        return ()
    try:
        open_ids = {int(item["id"]) for item in _state.worklist.open_items()}
    except Exception as exc:  # noqa: BLE001 - Tier-2: the page still goes out
        log.warning("could not read the worklist to check the page's item: %s", exc)
        return ()
    return (item_id,) if item_id in open_ids else ()


def _all_clear(alert: Alert, same_cause: list[Alert]) -> TriageResult:
    """The answer to a resolve, decided in code: an all-clear when this firing
    reached a phone, and silence when it never did.

    A page that asked the owner to act and then ended said nothing: the resolve fell
    in the five-minute dedup window, or the model read
    "already paged" and silenced it. A resolve has nothing
    to investigate, so no model is asked. `delivered_this_episode` reads only
    pages that really left, so nothing says "cleared" about one the owner never got,
    and a second resolve of the same episode finds the first and stays silent.
    """
    paged = _state.delivered_this_episode(alert.fingerprint)
    if not paged:
        return TriageResult(
            decision="silent", reason="resolve of a firing that never reached a phone"
        )
    what = str(alert.annotations.get("summary") or "").strip().rstrip(".") or alert.name
    if same_cause:
        what += f", and {len(same_cause)} more on the same path"
    ended = _local_clock(alert.ends_at) or "just now"
    # A resolve says only that the rule stopped matching. It also stops when
    # its subject goes away: a waiting-job page can resolve when a placeholder
    # is released while the job itself still waits, and then "needs no
    # action now" would be false. So the
    # all-clear states what the alert did and when, never that the problem
    # is gone.
    draft = (
        f"Stopped firing at {ended}: {what}. It was paged at "
        f"{_local_clock(paged)}. An alert also stops when its subject goes "
        "away, so this does not say the problem is solved."
    )
    return TriageResult(
        decision="enrich",
        reason=f"all-clear: resolved after the page delivered at {paged[:16]}Z",
        signal_draft=draft[:SIGNAL_MAX_CHARS],
    )


def _local_clock(text: str) -> str:
    """An ISO timestamp as HH:MM local time, or "" when it does not parse."""
    utc = _iso_utc(text)
    if not utc:
        return ""
    return datetime.fromisoformat(utc).astimezone(LOCAL_ZONE).strftime("%H:%M")


def _plumbing_gate(final: TriageResult, *, alert: Alert) -> TriageResult:
    """Keep openclaw's own bookkeeping out of a page without emptying the page.

    `claims.own_plumbing` was called from `morning_line` and nowhere else, and an
    acceptance rule asks that no rendered message carry a commit sha, so
    the guard belongs on every road that renders one. This road takes it with a
    floor, and the floor is not caution: it is measured.

    `_fallback_draft` puts the alert's FINGERPRINT in the page when the alert
    carries no summary, and a fingerprint is hex with digits in it, which is
    exactly what `_SHA_RE` matches. Run unguarded on that page the strip leaves
    "I am passing this on unchecked." and nothing else: a page with no news in
    it, which is the shape the house rules calls a bug. So the strip lands
    only when what survives still NAMES the alert; otherwise the draft goes out
    whole and the finding is logged. A page that says too much beats a page
    that says nothing, on the road whose whole job is to page.

    There is no nudge half here. Triage's nudge is a second `_brain.run`
    through the submit tool (`_causal_gate`), and spending another model call
    plus its latency on a presentation rule, on the paging path, buys less than
    it costs.
    """
    draft = final.signal_draft
    if not draft or not _claims.own_plumbing(draft):
        return final
    stripped = _claims.strip_own_plumbing(draft)
    if alert.name and alert.name not in stripped:
        log.warning(
            "triage draft reports openclaw plumbing but the strip would leave no "
            "news; sending it whole: %r",
            draft[:80],
        )
        return final
    return TriageResult(
        decision=final.decision,
        reason=final.reason,
        signal_draft=stripped[:SIGNAL_MAX_CHARS],
        tool_calls=final.tool_calls,
    )


@dataclass
class _Conversation:
    """One triage pass's model loop, kept so a gate can ask it once more.

    `response` and `payload` are the newest submit, so a second gate answers
    the call the model actually made last rather than the first one.
    """

    system: str
    messages: list[dict]
    dispatch: Callable[[str, dict], str]
    response: anthropic.types.Message
    payload: dict

    def ask(self, nudge: str) -> dict | None:
        """Answer the last submit with `nudge` and return the model's next
        submit, or None when it did not make one."""
        submit_id = next(
            block.id
            for block in self.response.content
            if getattr(block, "type", None) == "tool_use" and block.name == _tools.SUBMIT_NAME
        )
        self.messages.append({"role": "assistant", "content": self.response.content})
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": submit_id,
                        "content": nudge + " Then call submit_triage_decision again.",
                    }
                ],
            }
        )
        retry = _brain.run(
            system=self.system,
            messages=self.messages,
            tools=_tools.TOOL_DEFINITIONS,
            cap=3,
            dispatch=self.dispatch,
            terminal_tools=frozenset({_tools.SUBMIT_NAME}),
        )
        if not retry.finished:
            return None
        payload = _extract_submit(retry.response)
        if payload is None:
            return None
        self.response = retry.response
        self.payload = payload
        return payload


def _handover_gate(
    final: TriageResult,
    *,
    alert: Alert,
    conversation: _Conversation,
    given: str,
    read_text: list[str],
) -> TriageResult:
    """Keep a page from handing the reader a repair or a unit nothing read.

    `claims.unbacked_remedy` guards the pen, and without this the same road
    here would let "Need the watchdog restarted." through unchecked, with a
    unit the model invented. One
    nudge, as `_causal_gate` gives, then the offending sentences are stripped;
    a page never goes silent, so an emptied draft falls to the template.
    """
    if not final.signal_draft:
        return final
    # A repair is earned by what was READ, so the alert's own words do not back
    # one; a unit the alert names is a unit that exists.
    reads = "\n".join(read_text)
    seen = given + "\n" + reads
    nudge = _claims.unbacked_remedy(final.signal_draft, reads) or _claims.unread_unit(
        final.signal_draft, seen
    )
    if nudge is None:
        return final
    payload = conversation.ask(nudge)
    if payload is not None:
        final = _coerce_decision(payload, alert)
    if not final.signal_draft:
        return final
    kept = _claims.strip_unbacked_remedy(final.signal_draft, reads)
    kept = _claims.strip_unread_units(kept, seen)
    return TriageResult(
        decision=final.decision,
        reason=final.reason,
        signal_draft=(kept or _fallback_draft(alert))[:SIGNAL_MAX_CHARS],
    )


def _unread_stamp_gate(
    final: TriageResult, *, alert: Alert, given: str, read_text: list[str]
) -> TriageResult:
    """Page a critical silence whose reason rests on a stamp nothing read.

    A date, clock time or number in the reason that neither the alert as given
    nor any tool result of this pass contains is a guess, such as "commit
    6f6f6f6f at 13:55 UTC, 48s after alert fired" with no reading behind it. Only a critical, only a
    silence, and only after at least one read: `claims.unread_stamp` was kept
    checker-only because it also fires on honest arithmetic, and an error that
    pages is the cheap direction here.
    """
    if final.decision != "silent" or alert.status != "firing" or alert.severity != "critical":
        return final
    if not read_text:
        return final
    evidence = given + "\n" + "\n".join(read_text)
    sentences = _claims._SENTENCE_SPLIT_RE.split(final.reason)
    if not any(_claims.unread_stamp(sentence, evidence) for sentence in sentences):
        return final
    log.warning("triage silence on critical %s rests on an unread stamp", alert.name)
    return TriageResult(
        decision="page-raw",
        reason=f"silence on a critical cites a stamp nothing read (model said: {final.reason})",
        signal_draft=_fallback_draft(alert, prefix="[RAW] "),
    )


def _what_was_said(final: TriageResult) -> str:
    """The words a pass is held to: its page, or its reason for silence."""
    if final.signal_draft:
        return final.signal_draft
    return f"silent: {final.reason}"


def _causal_gate(
    final: TriageResult,
    *,
    alert: Alert,
    conversation: _Conversation,
    reads: dict,
    read_text: list[str],
) -> TriageResult:
    """Did-you-LOOK gate on the triage draft.

    A page that names a cause with zero successful reads is the confident
    wrong diagnosis this gate exists for. Triage has tools, so
    the nudge is real: answer the submit call with the nudge as its tool
    result and let the loop check or retract, then a mechanical symptom-only
    strip if it still diagnoses blind. Never blocks the page, every path
    returns a draft.

    It also gates a cause the reads DO NOT BACK, not only one
    with no reads behind it at all. `read_text` is what the tools returned; a
    gate that sees a bare count waves through anything above zero, which is
    true by construction on the path that produces confident wrong diagnoses.
    """
    if not final.signal_draft:
        return final
    evidence = "\n".join(read_text)
    # An issue number counts as read when any reading of this pass carries it,
    # in whatever form the tool printed it ("number: 42" from gh_issue_view).
    # Memory is not a reading: a number recalled from the journal is not backed.
    seen = _numbers_in(evidence)
    nudge = _claims.unbacked_causal_claim(
        final.signal_draft, reads["ok"], evidence
    ) or _claims.fabricated_issue_numbers(final.signal_draft, seen)
    if nudge is None:
        return final
    log.warning("triage draft named a cause or an issue its reads do not back; nudging")
    payload = conversation.ask(nudge)
    if payload is not None:
        final = _coerce_decision(payload, alert)
    draft = final.signal_draft
    if not draft:
        return final
    if _claims.unbacked_causal_claim(draft, reads["ok"], evidence):
        # Still diagnosing past what it read: page the symptom, drop the cause.
        # The evidence goes to the strip too, so a diagnosis a tool result
        # genuinely backs survives; only the invented ones go.
        draft = _claims.strip_causal_sentences(draft, evidence)
    draft = _claims.strip_unread_issue_sentences(draft, seen)
    if draft == final.signal_draft:
        return final
    return TriageResult(
        decision=final.decision,
        reason=final.reason,
        signal_draft=(draft or _fallback_draft(alert))[:SIGNAL_MAX_CHARS],
    )


def _numbers_in(evidence: str) -> set[int]:
    """Every free-standing number of two to five digits in what was read."""
    return {int(number) for number in re.findall(r"(?<!\d)\d{2,5}(?!\d)", evidence)}


# A silence reason that rests on a page having reached someone, or on one that
# will: "already paged twice", "already paged and delivered at 13:40", "rides
# into the morning brief instead". A model can write any of these when the
# delivery table says otherwise for the fingerprint it silences.
#
# "covered", "queued" and "subsumed" too: "covered by the queued page"
# leans on a page that may not have gone out yet, so it is checked like the
# rest. "already silenced" is not here on purpose: it says the
# condition resolved, not that anyone was told.
_PAGE_CLAIM_RE = re.compile(
    r"\b(?:paged|delivered|covered|queued|subsumed"
    r"|already\s+(?:flagged|sent|notified|reported|raised)"
    r"|morning\s+brief|brief\s+instead)",
    re.IGNORECASE,
)
# How many candidate covers the corrective turn lists.
_COVER_CANDIDATES = 8


def _page_claim_gate(
    final: TriageResult,
    *,
    alert: Alert,
    conversation: _Conversation,
    check_draft: Callable[[TriageResult], TriageResult],
) -> TriageResult:
    """Refuse a silence whose reason claims a page the table never delivered.

    The model writes its reason in free text, and unchecked, a silence could cite pages that never went out, or another fingerprint's
    delivery time. A claim stands only when the alerts table shows a
    delivered page on this fingerprint, or on the fingerprint the model named
    as `covered_by_fingerprint`, or when that page is still queued; the reason
    then carries the time code read. Otherwise the silence becomes a raw page,
    at every severity.

    Covering by another alert's page is kept, because that quieting is
    deliberate; it now has to name the page and the page has
    to exist. A model that described its cover only in prose is asked once to
    name it, from the pages that went out or are queued since this alert began.
    With no such page
    it pages at once. A page the model writes in answer goes through
    `check_draft`, the same checks as its first draft. The mechanical silences (dedup window, suppression)
    return from `triage()` before this runs, and Watchdog never claims anything.
    """
    if final.decision != "silent" or alert.status != "firing":
        return final
    if alert.name == "Watchdog" or not _PAGE_CLAIM_RE.search(final.reason):
        return final
    stands = _claim_stands(final, alert=alert, covered_by=_named_cover(conversation))
    if stands is not None:
        return stands
    candidates = _cover_candidates(alert)
    if candidates:
        payload = conversation.ask(_name_your_cover(candidates))
        if payload is not None:
            retried = _coerce_decision(payload, alert)
            if retried.decision != "silent":
                return check_draft(retried)
            if not _PAGE_CLAIM_RE.search(retried.reason):
                return retried
            stands = _claim_stands(retried, alert=alert, covered_by=_named_cover(conversation))
            if stands is not None:
                return stands
    log.warning("triage silence on %s claimed a page that never went out", alert.name)
    return TriageResult(
        decision="page-raw",
        reason=f"silence claimed a page nothing delivered (model said: {final.reason})",
        signal_draft=_fallback_draft(alert, prefix="[RAW] "),
    )


def _named_cover(conversation: _Conversation) -> str:
    """The covering fingerprint the model's newest submit names, or ""."""
    return str(conversation.payload.get("covered_by_fingerprint") or "").strip()


def _claim_stands(final: TriageResult, *, alert: Alert, covered_by: str) -> TriageResult | None:
    """The silence with the page code found behind its claim, or None when
    there is none: delivered or still queued on this fingerprint, delivered
    on the named cover, or the named cover still queued.

    A queued cover takes this fingerprint into its `covers`, so the release
    that sends it stamps this one delivered too."""
    # Quoted as it came. The time code read leads the reason and is the one to
    # trust; scrubbing the model's own times out left "paged at today." and
    # "today (,,)" in the audit.
    note = final.reason
    own = last_delivered_at(alert.fingerprint)
    if own:
        return TriageResult(
            decision="silent",
            reason=f"repeat; last delivered on this fingerprint at {own[:16]}Z (model said: {note})",
        )
    # A resend in quiet hours finds its own checked page waiting. Paging raw
    # here would hold a [RAW] draft under the same key, and the newest row per
    # key is the one released, so the checked page would be lost.
    own_queued = _state.pending_page_for_key(alert.fingerprint)
    if own_queued is not None:
        return TriageResult(
            decision="silent",
            reason=(
                f"repeat; own page queued since {str(own_queued['held_at'])[:16]}Z "
                f"(model said: {note})"
            ),
        )
    if not covered_by or covered_by == alert.fingerprint:
        return None
    covering = last_delivered_at(covered_by)
    if covering:
        return TriageResult(
            decision="silent",
            reason=(
                f"covered by the page on {covered_by} delivered at {covering[:16]}Z "
                f"(model said: {note})"
            ),
        )
    queued = _state.pending_page_for_key(covered_by)
    if queued is None:
        return None
    _state.add_page_cover(int(queued["id"]), alert.fingerprint)
    return TriageResult(
        decision="silent",
        reason=(
            f"covered by the queued page on {covered_by} held at "
            f"{str(queued['held_at'])[:16]}Z (model said: {note})"
        ),
    )


def _cover_candidates(alert: Alert) -> list[str]:
    """The pages that went out or wait in the queue since this alert started
    firing, one line each, newest first."""
    since = _iso_utc(alert.starts_at)
    lines = [
        f"{row['name']} [{row['fingerprint']}] delivered at {row['sent'][:16]}Z"
        for row in _state.delivered_pages_since(since, limit=_COVER_CANDIDATES)
    ]
    lines += [
        f"{row['subject']} [{row['key']}] queued since {str(row['held_at'])[:16]}Z"
        for row in _state.recent_held(_COVER_CANDIDATES)
        if row.get("key") and row["key"] != alert.fingerprint
    ]
    return lines[:_COVER_CANDIDATES]


def _name_your_cover(candidates: list[str]) -> str:
    """The corrective turn for a silence that described its cover in prose."""
    return (
        "Your silence claims an earlier page, but covered_by_fingerprint names "
        "none that was delivered or is queued. Pages delivered or queued since "
        "this alert started firing: " + "; ".join(candidates) + ". Name the one "
        "that covers this alert in covered_by_fingerprint, or page."
    )


def _iso_utc(text: str) -> str:
    """An Alertmanager timestamp as the table writes one, or "" unparseable."""
    try:
        moment = datetime.fromisoformat((text or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


# How many judged silences the same never-heard critical gets before triage
# stops asking. `monitor/limits.py::STILL_DOWN_REPAGE_EVERY` re-raises a stuck
# component hourly for exactly this reason: a wrong silence was permanent. That
# reasoning was applied to the component sweep and never to the alert path,
# which is where it bites: a critical can keep firing for over an hour, be
# judged away on every arrival, and leave every audit row `silent` with
# `signal_sent_at` NULL. Nothing reaches a phone.
#
# 2 and not 3: measured against a real audit of several months, 2 forces a
# handful of extra pages and all of them are real, while 3
# fires never, because interleaved resolved rows break a firing-only streak.
_UNHEARD_SILENCE_FLOOR = 2

# The second trigger, which does not wait for Alertmanager to re-deliver: a
# critical that has been firing this long with nothing ever delivered on its
# fingerprint gets one page on the strength of its age alone: an alert that
# started at 14:25 is spoken at 14:55, half an hour into the outage.
_UNHEARD_AGE_MINUTES = 30


def _unheard_too_long(alert: Alert) -> bool:
    """Has this alert been firing longer than the floor's patience?

    An unparseable or absent `startsAt` reads as not-yet-old: the streak
    trigger still covers it, and a clock the gate could not parse is no reason
    to page.
    """
    text = (alert.starts_at or "").strip()
    if not text:
        return False
    try:
        started = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - started
    return age >= timedelta(minutes=_UNHEARD_AGE_MINUTES)


def _silence_floor(final: TriageResult, *, alert: Alert) -> TriageResult:
    """The floor under a judged silence on a critical nobody has ever heard.

    It never argues with the FIRST silence, and it edits no prompt: the
    quieting the model does from `outbound.recent_sent` is deliberate
    and most critical silences come from it. What it
    refuses is letting the same never-heard critical be judged away twice, or
    letting one sit unheard for half an hour.

    Out of scope by construction: a resolve, Watchdog, anything below critical,
    and any fingerprint that has ever delivered a message. The two mechanical
    silences (dedup window, operator suppression) return from `triage()` before
    this runs, so a human's mute is never overridden and an Alertmanager retry
    storm cannot manufacture a streak; the reason check below is the belt on
    that placement. Returns `final` untouched whenever the floor does not
    apply.
    """
    if final.decision != "silent":
        return final
    if alert.status != "firing" or alert.severity != "critical":
        return final
    if alert.name == "Watchdog":
        return final
    if final.reason == "dedup-window-hit" or final.reason.startswith("suppressed:"):
        return final
    if _state.has_delivered(alert.fingerprint):
        return final
    # `gates/app._record_alert` writes the audit row AFTER the send is
    # attempted, so the current silence has no row yet: one prior unheard
    # judgement plus this one is the second.
    silences = _state.unheard_silences(alert.fingerprint) + 1
    streak_hit = silences >= _UNHEARD_SILENCE_FLOOR
    if not streak_hit and not _unheard_too_long(alert):
        return final
    forced_by = (
        f"{silences} unheard silences"
        if streak_hit
        else f"unheard for {_UNHEARD_AGE_MINUTES}+ minutes"
    )
    log.warning("silence floor forcing a page on %s (%s)", alert.name, forced_by)
    return TriageResult(
        decision="page-raw",
        reason=(
            f"floor: {forced_by} on a critical that has never paged "
            f"(model said: {final.reason})"
        ),
        signal_draft=_fallback_draft(alert, prefix="[RAW] "),
    )
