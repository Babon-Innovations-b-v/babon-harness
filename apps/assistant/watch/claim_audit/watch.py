"""The timer entrypoint: ask the container for the week's audit, post it to Talk.

TALK, NEVER SIGNAL, and here the reason is sharper than usual. This report is
about the assistant sending too many messages that nobody could check. Putting it on
the phone would be one more of them, on the surface it is complaining about.
Same rule as `core/monitor/dead_letters.py`;
different reason from both.

WHERE THE DELIVERY RUNS. `shared.notify.post_talk` needs NC_ALERTS_USER,
NC_ALERTS_PASSWORD and NC_ALERTS_ROOM, which the server's environment file
carries for every scheduled job, so the weekly report is posted from out
here.

The same gap can leave `core/monitor/dead_letters` posting into a void, and
nothing here would find out: what finds out is the watch putting its own
channel failure in the notify pen. A suspicion written in a docstring is not a
detector.

THE EXIT CODE IS THE SAME DELIBERATE INVERSION. A week full of findings exits
0. Exiting non-zero fires `harness-notify-failure@`, which pages Signal with a journal
tail, and that is precisely the page this design avoids. The one thing that
exits non-zero is a report that reached nobody at all: at that point Signal
beats silence, and it is the only case in this module where Signal is right.

FAILURE POLICY: Tier-2 on the record, fail-loud on the fetch. A window that
could not be read is never posted as an empty week.
"""
from __future__ import annotations

import logging
import os
import sys
import time

from apps.assistant.watch.claim_audit import fetch, metrics, summary

log = logging.getLogger("openclaw.claim_audit")


def _post_to_talk(subject: str, body: str) -> bool:
    """Send the report to the Talk room. True when it landed."""
    from apps.assistant.shared import notify

    result = notify.fan_out(subject, body, signal=False)
    return bool(result.get("talk"))


def _keep_the_record(audit: fetch.Audit) -> None:
    """Publish the metric so a bad week is a number and not only a post.

    Tier-2 and deliberately so: a textfile directory this process cannot write
    must not cost the Talk post that follows.
    """
    try:
        metrics.publish(
            metrics.render(
                messages=audit.messages,
                findings=audit.findings,
                unbacked=summary.unbacked_count(audit.report),
                at=time.time(),
                road_shares=audit.road_shares,
                uncounted_roads=audit.uncounted_roads,
                unheard=audit.unheard,
                unheard_critical=audit.unheard_critical,
                held=audit.held,
            )
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: the record is not the run
        log.error("could not publish the claim-audit metric (swallowed): %s", exc)


def main() -> int:
    """One weekly tick. Returns 0 unless the report reached nobody."""
    audit = fetch.fetch(os.environ.get(fetch.SECRET_ENV, ""))
    print(audit.report)
    _keep_the_record(audit)

    if audit.findings == 0 and audit.messages:
        log.info(
            "claim audit clean over %d message(s); nothing posted to Talk",
            audit.messages,
        )
        return 0
    # A window with NO messages in it is not a clean week and must never be
    # posted as one. The morning brief sends Monday to Friday whatever happens
    #, so a week the assistant said nothing at all in is a week the
    # pod was dead or the recording stopped, and `remember_readings` swallows
    # its own write faults on purpose, so a broken table would look exactly like
    # a quiet week and say nothing forever. `render.report` already leads with
    # "No messages recorded between ..."; this is what puts that line in front
    # of a person. Talk, not a page: it is worth reading on Monday and it is not
    # worth a phone at two in the morning.

    subject = summary.subject(audit)
    try:
        if _post_to_talk(subject, audit.report):
            log.warning("reported to Talk: %s", subject)
            return 0
    except Exception as exc:  # noqa: BLE001 - never mask the real result
        log.error("Talk post raised: %s", exc)
    # Nothing reached a human. Exit loud so `harness-notify-failure@` takes over.
    print(f"could not deliver the claim audit to Talk: {subject}", file=sys.stderr)
    print(audit.report, file=sys.stderr)
    return 1
