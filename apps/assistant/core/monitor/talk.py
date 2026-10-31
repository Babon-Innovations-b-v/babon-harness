"""The package's one way out, and the one place a channel's answer is read.

WHY THIS FILE EXISTS. `notify.fan_out(..., signal=False)` does not raise when
a channel fails, it logs and hands back a per-channel dict, so a caller that
throws the return value away cannot tell a report nobody received from one
that landed.

The container's whole environment comes from the environment file, and when
NC_ALERTS_USER, NC_ALERTS_PASSWORD and NC_ALERTS_ROOM are missing from it,
`notify.post_talk` logs "Talk creds not configured" and returns False, and
`signal=False` means there is no second leg: a watch can post into nothing for
as long as it exists. `nobody_can_be_told` puts the channel's own failure in
the notify pen, which is the road below. The three keys are listed in
`config/vault.env.example` and reach the container through
`apps/assistant/compose.yml`; NC_URL does not need to be set, `post_talk`
defaults it.

Do not read this as the reporting path being proven. It is proven for the one
room those credentials name, on the day someone checks it. The read below is
what would tell us it broke, which is why it stays and why nothing here trusts a channel to have
worked.

TALK, NEVER SIGNAL. A dead letter is by definition a message Signal did not
take, so a Signal report about dead letters joins them. That reasoning is the
package's, not this file's.

WHAT HAPPENS WHEN NOBODY TAKES IT. Two options were on the table and both were
rejected as written.

  Escalate to Signal. The Signal credentials ARE in the Secret, so it would
  work. Rejected on three counts. Signal is the channel a dead letter says just
  failed, so the escalation would file its report behind the failure it is
  reporting. Inside the container `OPENCLAW_GATEWAY_SELF=1` makes a Signal leg a
  signal-cli DIRECT send, which is the second private line to the same phone
  that was taken out of this package: no rate limit, no dedup key, no
  cooldown stamp, no quiet hours, no story gap. And the test above exists to stop precisely that line
  coming back; one watch is not a good enough reason to reopen it.

  Refuse loudly at boot when the credentials are absent. Rejected as written and
  kept in spirit. As written it means this package reading NC_ALERTS_* out of
  the environment, which copies `notify.post_talk`'s own configuration knowledge
  into a module that must not depend on it, and it catches only the credentials
  being ABSENT: not a wrong room id, not a stale password, not Nextcloud being
  down. The first report that reaches nobody proves everything the boot check
  proves and more, and it proves it from the channel's own answer rather than
  from a guess about what the channel needs.

So: read the dict, hand the caller the channels that accepted, and let the
caller keep its finding rather than bank it. Once per process, put the channel's
own failure in the notify pen, which is the road this package is allowed to use
(`sweep._queue_ping`) and the road that owns dedup, quiet hours, the story gap
and the recurring filer. A configuration fault that survives pod restarts costs
about three pages there and then becomes a card on the board.

ONCE PER PROCESS AND NOT ONCE PER PASS, because the alternative amplifies. The
pen's own send is Signal; a pen page that fails writes a dead-letter row; that
row is exactly what `dead_letters.check` reads. One ping per sweep during a
Signal outage would add a ping a minute about the failure to report the failure.
A per-process bound holds without depending on anything else working.

FAILURE POLICY: Tier-2 throughout. Reporting must never take the runner down,
so every send and every write here is defended and the answer comes back as a
value.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import logging

from apps.assistant.core import outbound, state

log = logging.getLogger("openclaw.monitor.talk")

# Same source as the sweep's pings: to the pen these are the stack monitor
# speaking, whatever inside the package wrote them.
PING_SOURCE = "stack-monitor"

# Error, not critical, and for the reason the overlay already gives for the
# sweep's pings: what this package knows is that it could not reach something,
# which is a smaller claim than the deploy gate's about its own verdict.
_SEVERITY_MARKER = "❌"

# Whether the channel's own failure has been put in the pen in this process.
_deaf_reported = False


def reset() -> None:
    """Test hook: forget that the channel failure was already reported."""
    global _deaf_reported
    _deaf_reported = False


def report(subject: str, body: str) -> tuple[str, ...]:
    """Post one report and return the channels that ACCEPTED it.

    An empty tuple means the report reached nobody. It is a value a caller has
    to handle and not one it may ignore, because it is the only thing that
    separates a watch which reported from a watch which succeeded at nothing.
    """
    try:
        from apps.assistant.shared import notify

        result = notify.fan_out(subject, body, signal=False)
    except Exception as exc:  # noqa: BLE001 - Tier-2: never break the runner
        log.error("report raised, so nobody was told: %s: %s", subject, exc)
        return ()
    try:
        accepted = tuple(
            str(channel) for channel, took_it in dict(result).items() if took_it
        )
    except (TypeError, ValueError):
        # A channel that answers with something other than a per-channel map
        # says nothing about delivery, and "says nothing" is not "delivered".
        log.error("report answered %r, which does not say who took it", result)
        return ()
    if not accepted:
        log.error("NOBODY TOOK THE REPORT: %s", subject)
    return accepted


def nobody_can_be_told(watch: str) -> bool:
    """Put the reporting channel's own failure in the pen, once per process.

    Returns True when this call queued it, False when this process already has
    or when the pen would not take it either. The flag is set BEFORE the write,
    so a pen that is also broken costs one attempt and not one per sweep.
    """
    global _deaf_reported
    if _deaf_reported:
        return False
    _deaf_reported = True
    subject = f"{_SEVERITY_MARKER} {ASSISTANT_NAME} cannot report: no channel took the report"
    body = "\n".join(
        (
            f"Watch: {watch}",
            "Channel: Nextcloud Talk, with the Signal leg deliberately off",
            "Effect: the watch is holding its finding and retries every sweep",
        )
    )
    try:
        state.enqueue_ping(subject, body, PING_SOURCE)
        log.error("queued the channel failure in the pen, raised by %s", watch)
        return True
    except Exception as exc:  # noqa: BLE001 - Tier-2: never break the runner
        # Same shape as `sweep._queue_ping`: a pen write that fails loses the
        # page, so it is recorded as a dead letter rather than only logged.
        log.error("channel failure not queued (swallowed): %s", exc)
        outbound.record_delivery("monitor-page", subject, False)
        return False
