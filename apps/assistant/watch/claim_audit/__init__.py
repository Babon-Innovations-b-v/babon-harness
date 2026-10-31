"""Deliver the assistant's weekly claim audit, VM-side, to Nextcloud Talk.

The checking is pod-side, in `apps/assistant/core/claim_audit/`: the
rules live next to the guards they borrow, and a rule read at two moments is
the whole idea. This package is only the delivery, and it is out here for a
reason that has since been fixed: `shared.notify.post_talk` needs
NC_ALERTS_USER, NC_ALERTS_PASSWORD and NC_ALERTS_ROOM, the container's only env
source is the environment file, and nothing synced those three
into it. The compose file now passes them in from the vault, so the
delivery could move in. It has not, because where a weekly timer lives is not what this package
is for, and the reason to move it would have to beat the reason it is here.

Module map (one public concern per file):

    fetch.py    `fetch(secret) -> Audit`: POST `/webhook/claim-audit` and bring
                the report back. Its own HTTP call, because `watch/trigger`
                returns None by design and cannot carry an answer
    summary.py  `subject(audit)` / `unbacked_count(report)`: the Talk subject,
                and the one number the metric reads back out of the report
    metrics.py  `render()` / `publish()`: the outcome as a node-exporter
                textfile, so a bad week is a number and not only a post
    watch.py    `main()`: the timer entrypoint, exit 0 whatever the report says
    __main__.py `python -m apps.assistant.watch.claim_audit`

TALK, NEVER SIGNAL. The report is about the assistant sending too many messages that
nobody could check; putting it on the phone would be one more of them. A week
full of findings still exits 0, so `harness-notify-failure@` cannot page about it. Only
a report that reached nobody exits non-zero, and there Signal beats silence.

FAILURE POLICY: fail-loud on the fetch, Tier-2 on the record. An audit that
answers "nothing to report" for a window it could not read is the one wrong
answer nobody questions, so a broken fetch is a visibly failed timer.
"""
from __future__ import annotations

# Re-exported as the submodules (not their callables): `fetch`, `subject`,
# `render` and `publish` are generic verbs that collide across this tree;
# callers use `fetch.fetch(...)`, `metrics.publish(...)`.
from apps.assistant.watch.claim_audit import (
    fetch,
    metrics,
    summary,
    watch,
)

# The signature type rides with its callable and IS re-exported flat
#.
from apps.assistant.watch.claim_audit.fetch import Audit

__all__ = ["Audit", "fetch", "metrics", "summary", "watch"]
