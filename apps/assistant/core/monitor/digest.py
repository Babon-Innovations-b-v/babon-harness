"""Digest the sweep's state changes into ONE plain-text Signal message
processed by openclaw's brain.

External contract: a single `digest_transitions(transitions) -> str | None`
entry point. It takes the batch of `Transition`s from ONE sweep and runs
the SAME bounded read-only LLM tool-use loop as `core.chat` (no
submit-tool, the final assistant text IS the message): for the
components that went DOWN it investigates the likely CAUSE with the
read-only tools and judges real-vs-noise/expected (a GPU serving pod
Pending because the GPU node scaled to 0 is EXPECTED; a component
"down" only because a misconfigured healthcheck failed while it's
actually reachable is NOT a real outage), then writes one short
plain-text message telling the owner only what they need to know, grouped,
broken-thing-and-cause first, recoveries folded in. If nothing is worth
paging it replies the bare token `SILENT` and we return None.

Why a NEW module and not a per-transition page: raw "DOWN: <component>" lines
are still alerts, not processing; a reader wants only what they need to know.
This is the processing step.

THE CALLER USES THE VERDICT AND NOT THE MESSAGE.
The sweep no longer sends anything itself; a down component becomes a ping
in the notify pen and the pen renders the page from templates a person
wrote, so prose written here reaches nobody. What is
still load-bearing is the judgement, and specifically one thing nothing
else in the stack can do: the tools below let this loop ask what just
landed, so it can tell the container that restarted because a deploy touched it
from the one that broke, and the GPU pod Pending because its node pool
scaled to nothing from an outage. The pen's own model gets typed fields
and no tools at all, so it cannot make that call. Returning None here is
what keeps deploy churn off the phone; returning anything at all sends the
batch to the pen, and the message is logged there rather than shipped.

The metered tool-use loop itself lives in `core.brain` (shared by every
The assistant loop); the digest supplies the read-only tool surface (chat's
definitions minus the triage submit-tool), `LLM_MAX_ITERATIONS`, and its
own terse fallback for every non-`finished` outcome.

FAILURE POLICY: Tier-2 degrade, NEVER drop a real death. If the budget is
tripped we skip the LLM entirely and return a terse summary built
straight from the transitions (a death is never silenced just because the
brain is out of budget). On `anthropic.APIError`, same terse fallback
(a brain outage must not lose a death). That fallback says the same facts
in the same voice as a real digest, and says that nothing investigated
them; it is deliberately not the raw "DOWN: x, y" line this module was
built to remove. The iteration cap and an empty/no-progress model
response also fall back to the terse summary. Only an explicit `SILENT`
(or a digest with zero down transitions and nothing to say) returns None.
The budget reads/charges are Tier-1 and propagate, see `core.state`.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import json
import logging

from apps.assistant.core import brain as _brain
from apps.assistant.core import self_context as _self_context
from apps.assistant.core import signal_text as _signal_text
from apps.assistant.core import tools as _tools
from apps.assistant.core.limits import LLM_MAX_ITERATIONS
from apps.assistant.core.monitor.component import DOWN as _DOWN, UP as _UP

log = logging.getLogger("openclaw.monitor.digest")

# `SILENT` is the model's "nothing worth paging" token. The model is told to
# reply with EXACTLY this token, but in practice it often writes its reasoning
# first and then puts `SILENT` on its own final line ("looked, intentional
# scale-down, nothing actionable\n\nSILENT"). We therefore treat the message as
# silent when its LAST non-empty line is exactly the token, not only when the
# whole message equals it. A real page never ends with a lone `SILENT` line, so
# this can't accidentally silence a death; the stricter whole-message-only check
# would instead SEND the reasoning paragraph as a false page.
_SILENT_TOKEN = "SILENT"


def _digest_tool_definitions() -> list[dict]:
    """Investigation tools only, same surface as core.chat (drop the triage
    submit-tool). The digest's output is plain assistant text, no decision to
    submit.

    Built lazily (not at import time) because the monitor package seam pulls
    `digest` in while `core.tools` is still initialising via
    `tools.stack_status -> monitor.registry`; reading `TOOL_DEFINITIONS` at
    import time would hit a partially-initialised tools module (circular
    import)."""
    # read-only investigation surface only (no write tools), the house rules
    # guarantee, now a property of this one call.
    return _tools.investigation_definitions()

_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, monitoring the team's stack.

These stack components just CHANGED STATE in one monitoring sweep. Your job is
to process this for the owner, not relay it. They do not want a list of raw
"DOWN: x" lines; tell them only what they actually need to know.

For every component that went DOWN, use your read-only investigation tools to
find the likely CAUSE, and judge whether it is a REAL, actionable problem or
just noise / expected behaviour. Examples of NOT a real outage:
- a GPU serving pod stuck Pending because the GPU node pool scaled to 0 after a
  scale-down, that is expected, the pool spins up on demand;
- a component that is actually reachable but tripped a misconfigured or flaky
  healthcheck, not a real outage;
- a brief blip that already recovered in the same batch.
A real outage is a public surface or in-cluster workload that is genuinely
unreachable / crashed / unschedulable for a real reason (OOM, image pull error,
config error, DB down, deploy gone bad).

A component going down right as a deploy lands is usually a restart, not an
outage, check that FIRST: `gh_commits` shows what just landed, and
`gh_changed_files` shows which files/services that deploy touched, so you can
tell "the pod that restarted is exactly the one that deploy changed" (expected)
from "something unrelated broke" (real).

A deploy restart that is progressing normally is SILENT, full stop. New image
pulling, pod Running and working through its startup probe inside its window,
then coming back, that is routine deploy work, and it belongs in the daily
report, NOT a mid-day message. A service that is rebuilt on every deploy
restarts on every deploy, so its restarts are the most routine churn there
is. Do not send a page about one, not even a reassuring "it's mid-restart,
nothing to act on" note: that reassurance is exactly the noise the owner does
not want. Page a restart ONLY if it is stuck past
its startup window, crash-looping, or no deploy explains the down.

Available investigation tools (read-only): `kubectl_get`, `kubectl_describe`,
`kubectl_logs`, `kubectl_events` (cluster state); `gh_issue_view`,
`gh_issue_list`, `gh_pr_view`, `gh_commits` (in-flight work + what just landed),
`gh_changed_files` (which files a commit/deploy touched, deploy correlation);
`db_query` (SELECT-only ops Postgres: runs/ops_activity/alerts/deploys);
`loki_query` and
`prom_query` (logs + metrics); `stack_status` (the authoritative live
stack-liveness view). Use them sparingly, every call costs tokens, and you
only need enough to name the cause.

Then write ONE message to the owner:
- Lead with what is ACTUALLY broken and the cause you found.
- Group related components (e.g. several pods down for one root cause = one line
  about that cause, not one line per pod).
- Fold a recovery in ONLY if you are already paging its outage in this same
  message ("...; back up: x"). A lone "back up: x" for something that went down
  and recovered on its own, or as part of a deploy restart you would not have
  paged, is SILENT: you never paged the down, so you never page the "back up".
- A "down" that turned out to be noise, expected, or a deploy restart gets NO
  message, not even a reassuring "looked at it, all fine" line. That mid-day
  reassurance is the noise the owner does not want; it rides the daily report. Drop
  it.

If, after investigating, NOTHING in this batch needs the owner NOW (all noise /
expected / deploy restarts / lone recoveries / already-recovered with nothing
actionable), output exactly <note>SILENT</note>. A batch that is only deploy
restarts and their recoveries is always SILENT.

You may think out loud first. But your ACTUAL message to the owner must be wrapped
in <note> and </note> tags, and ONLY the text inside the tags is sent to their
phone, so put the finished page inside them and nothing else inside them: no
preamble, no "here's the message", no reasoning.

Inside the tags: plain text only. Signal shows markdown literally, so NO
asterisks, backticks, emoji, bullet characters, headings, or divider rules.
Write it in YOUR VOICE (block above): a flowing message from a colleague,
continuing the thread with what you already sent; generous length is fine if
there is genuinely a lot to say."""


def _format_transitions_for_llm(transitions: list) -> str:
    """Serialise the batch into the user turn the model reads."""
    return json.dumps(
        [
            {
                "component": transition.component,
                "group": transition.group,
                "old_status": transition.old_status,
                "new_status": transition.new_status,
                "detail": transition.detail,
            }
            for transition in transitions
        ],
        indent=2,
    )


def _joined(names: list[str]) -> str:
    """A list of component names as a person writes one: "a, b and c"."""
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _terse_fallback(transitions: list) -> str:
    """The brainless summary, used when the LLM cannot run (budget tripped,
    Anthropic fault, iteration cap, no progress).

    Built straight from the transitions so a real death is NEVER silently
    dropped. It is not the raw "DOWN: x, y" line, which is the exact line
    this module exists to replace: the docstring above says those lines are
    alerts rather than processing, and the prompt tells the model not to write
    them. Sending one whenever the model is out is
    the rule holding on the good path and breaking on the bad one.

    Same facts, in sentences, and it says out loud that nothing looked into it,
    because that is the one thing a reader needs to know about a fallback page:
    the cause line they are used to is missing because nobody could go and get
    it, not because there was nothing to find.
    """
    downs = [t.component for t in transitions if t.new_status == _DOWN]
    recoveries = [
        t.component
        for t in transitions
        if t.new_status == _UP and t.old_status == _DOWN
    ]
    lines: list[str] = []
    if downs:
        lines.append(
            f"I cannot reach {_joined(downs)} right now, and I could not look "
            "into why."
        )
    if recoveries:
        lines.append(f"{_joined(recoveries)} came back.")
    return " ".join(lines)


def digest_transitions(transitions: list) -> str | None:
    """Process one sweep's batch of transitions into ONE plain-text Signal
    message, or None if nothing is worth paging.

    Runs the bounded read-only LLM tool-use loop (the `core.chat` shape) so
    the brain investigates the down components and decides what the owner needs to
    see. Tier-2: if the budget is tripped or Anthropic faults, we never lose a
    death, we fall back to a terse raw summary built from the transitions.
    """
    if not transitions:
        return None

    messages: list[dict] = [
        {"role": "user", "content": _format_transitions_for_llm(transitions)}
    ]
    system = _self_context.render("digest", _SYSTEM_PROMPT)
    outcome = _brain.run(
        system=system,
        messages=messages,
        tools=_digest_tool_definitions(),
        cap=LLM_MAX_ITERATIONS,
        dispatch=lambda name, tool_input: _tools.execute(name, tool_input),
    )
    # Never lose a death: a tripped budget, an Anthropic fault, or the cap all
    # degrade to the terse raw summary rather than silence.
    if not outcome.finished:
        log.info("digest falling back to terse summary (%s)", outcome.status)
        return _terse_fallback(transitions) or None

    message = _signal_text.strip_markdown(
        _signal_text.extract_note(_signal_text.text_of(outcome.response))
    )
    if _signal_text.is_sentinel(message, _SILENT_TOKEN):
        return None
    if not message:
        # Empty final response, don't drop a death, fall back.
        log.warning("digest produced empty message; falling back")
        return _terse_fallback(transitions) or None
    return message
