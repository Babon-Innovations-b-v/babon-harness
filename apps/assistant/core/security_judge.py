"""Security paging JUDGMENT, reasoning, not a threshold.

A threshold such as "wrong-key count >= 10 -> page" fires on our own
webhook-secret rotation (the emitter re-authing with the old key) and
cries "someone's guessing the secret" when nothing of the sort is
happening. A real assistant would not do that: it would notice the burst
started right after a deploy/rotation, check, and conclude it's internal.

So this is a judgment pass, not a rule. Given the security activity it
REASONS, is this new or already said, real or something we caused,
worth interrupting the owner now or a footnote for the morning brief, and
it may USE READ-ONLY TOOLS to check first (recent deploys/commits, the
stack, what changed) before deciding. It outputs a plain-language message
to send NOW, or QUIET (nothing / note it for later). The counts and the
cooldown are only inputs and a rate backstop, never the decision.

`judge_security(bad_bearer, unauth, senders) -> str | None`.

FAILURE POLICY: Tier-2 advisory. Budget tripped or Anthropic faulted ->
return None (stay quiet) rather than fall back to a dumb threshold page;
a missed judgment is better than a false alarm. Budget is Tier-1.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import logging

from apps.assistant.core import brain as _brain
from apps.assistant.core import self_context as _self_context
from apps.assistant.core import signal_text
from apps.assistant.core import tools as _tools
from apps.assistant.core.limits import PATROL_MAX_ITERATIONS
from apps.assistant.core.tools.agenda import calendars as _calendars

log = logging.getLogger("openclaw.security_judge")

_QUIET_TOKEN = "QUIET"

_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, deciding whether some security activity on
your own webhook is worth telling the team about. This is a JUDGEMENT, not a
rule, do NOT page just because a count is high.

Reason it through before you decide, and CHECK with your read-only tools:
- Is it real or something WE caused? A burst of wrong-key 401s right after a
  deploy or a webhook-secret rotation is almost always our own service
  re-authing with the old key, NOT an attacker. Use deploy_status / gh_commits
  / gh_changed_files to see if anything just shipped or rotated. If it lines up
  with our own change, it is internal, do NOT cry "someone is guessing the
  secret".
- Is it NEW, or did I already say it? Your recent messages are in the block
  above. Don't repeat yourself.
- Does it need the owner NOW, or is it a footnote for the morning brief? Only
  interrupt for something genuinely worth interrupting: a sustained external
  attack, an actual breach attempt from an unknown source. A handful of
  bounced 401s that we caused is not worth a ping.

Then decide. If it's worth telling the owner now, write ONE short plain-text
message in your voice (a calm heads-up, what you checked, what you concluded).
If it's internal, expected, already-said, or just not worth it, output exactly
QUIET.

Plain text only (Signal shows markdown literally). Wrap your final message in
<note> and </note>; put ONLY the message inside, or <note>QUIET</note>."""


def _tool_definitions() -> list[dict]:
    # read-only investigation surface only (no write tools), the house rules
    # guarantee, now a property of this one call.
    return _tools.investigation_definitions()


def judge_security(bad_bearer: int, unauth: int, senders: list[str]) -> str | None:
    """Reason about the current security activity and return the message to
    send now, or None (quiet). Read-only tools available so it can check
    whether the burst is internal before deciding."""
    facts = (
        f"Security activity to judge:\n"
        f"- wrong-key (401) attempts in the last 10 min: {bad_bearer}\n"
        f"- non-allowlisted chat attempts in the last 15 min: {unauth}"
    )
    if senders:
        facts += f" from {', '.join(senders)}"
    facts += (
        "\n\nDecide whether this is worth telling the owner now. Check first whether "
        "it lines up with a recent deploy or webhook-secret rotation (then it's "
        "our own service, not an attacker)."
    )
    messages: list[dict] = [{"role": "user", "content": facts}]
    # Same reason as patrol: nobody is speaking here, and agenda_view is on
    # this loop's surface, so a speaker left by the last chat turn must not
    # decide whose calendar an autonomous read sees.
    _calendars.set_speaker(None)
    system = _self_context.render("security", _SYSTEM_PROMPT)
    outcome = _brain.run(
        system=system,
        messages=messages,
        tools=_tool_definitions(),
        cap=PATROL_MAX_ITERATIONS,
        dispatch=lambda name, tool_input: _tools.execute(name, tool_input),
        recheck_budget=True,
    )
    # Advisory: a tripped budget, an Anthropic fault, or the cap stay quiet
    # rather than fall back to a dumb threshold page.
    if not outcome.finished:
        log.info("security judgement skipped (%s)", outcome.status)
        return None
    note = signal_text.strip_markdown(
        signal_text.extract_note(signal_text.text_of(outcome.response))
    )
    if not note or signal_text.is_sentinel(note, _QUIET_TOKEN):
        return None
    return note
