"""Page when a page did not arrive.

A dead letter is the assistant deciding to tell someone something, and nobody
receiving it. It is the quietest failure in the system: the audit row shows a
sensible decision, the reasoning was right, and the human simply never hears
it. If every send dead-letters for hours, a page as important as "the disk
is 100% full" is found the next day by a person rather than by the system.

Deliberately NOT part of `run_sweep`. The sweep is the paging path; this is a
check ON that path, so it stays its own module and the runner calls both. A
bug here can leave the sweep untouched.

Routed to Nextcloud Talk ONLY, through `talk.report`. Signal is by definition
the channel that just failed, so a Signal page about dead letters would join
them. Same reasoning as the two deadman switches keeping off the openclaw path.

THIS WATCH MUST NOT BE ABLE TO SUCCEED AT NOTHING. A watch that ignores the
per-channel dict `notify.fan_out` returns, advances the watermark BEFORE
knowing whether anything was delivered, and returns the row count either way
would, on a deployment without NC_ALERTS_* credentials, send every report
nowhere, count it as sent, and take its rows out of reach in the same pass.
So two properties hold. The
watermark advances only when a channel accepted the report, so an undelivered
finding comes back on the next sweep and keeps coming back until it lands. And
the pass says which of the three states it is in: nothing to report is
`check() == 0`, a delivered report is `check() > 0` with `stranded() == 0`, and
a report that reached nobody is `check() > 0` with `stranded() > 0`. The reasons
behind the channel choice, and the two alternatives rejected, are argued in
`talk.py`.

The watermark starts at the newest row at process start, so a restart reports
what happens next and never replays history. It lives in memory on purpose:
losing it on restart costs nothing, and persisting it would mean another write
on the path that is already failing.

FAILURE POLICY: Tier-2. Every read and the report are defended; the runner must
keep sweeping even if this check is broken. What it must never do is report a
fault as an absence, which is why a defended failure leaves the rows stranded
instead of returning zero.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import logging

from apps.assistant.core import state
from apps.assistant.core.monitor import talk

log = logging.getLogger("openclaw.monitor.dead_letters")

# Newest audit row already accounted for. None until the first call, which
# seeds it from the table rather than from zero.
_watermark: int | None = None

# Dead letters this watch found and no channel would take. Held, not banked.
_stranded: int = 0


def reset(watermark: int | None = None) -> None:
    """Test hook: seed or clear the watermark and the stranded count."""
    global _watermark, _stranded
    _watermark = watermark
    _stranded = 0


def stranded() -> int:
    """How many found dead letters no channel has accepted a report about.

    Zero both when there was nothing to report and when the report landed; the
    pair `(check(), stranded())` is what tells those two apart from a report
    that reached nobody.
    """
    return _stranded


def check() -> int:
    """Report any new dead letters to Talk. Returns how many were FOUND.

    Found, not delivered: `stranded()` answers how many of them reached nobody.
    The count is the watch's own reading of the audit table, so it stays a true
    number even when the channel is broken, which is the case the container is
    actually in.
    """
    global _watermark, _stranded
    try:
        if _watermark is None:
            _watermark = state.max_alert_id()
            return 0  # first pass only establishes "from here on"
        rows = state.dead_letters_after(_watermark)
    except Exception as exc:  # noqa: BLE001, Tier-2: never break the runner
        log.warning("dead-letter read failed: %s", exc)
        return 0
    if not rows:
        _stranded = 0
        return 0

    names = []
    for row in rows:
        name = str(row.get("name", "?"))
        if name not in names:
            names.append(name)
    body = (
        f"{len(rows)} page(s) were decided and never delivered: "
        f"{', '.join(names)}.\n\n"
        f"Signal accepted none of them, so anything {ASSISTANT_NAME} tried to tell you in "
        "that window did not arrive. Check the send path first "
        "(harness-signal-send-canary, then the VM disk: a full data disk stops "
        "signal-cli extracting libsignal)."
    )
    accepted = talk.report(f"🔴 [the project] {ASSISTANT_NAME} pages are dead-lettering", body)
    if not accepted:
        # The watermark stays where it is: these rows have not been reported to
        # anybody, so banking them here is the same defect one layer up.
        _stranded = len(rows)
        log.error(
            "%d dead-lettered page(s) reached nobody and are held for the next "
            "pass: %s",
            len(rows),
            ", ".join(names),
        )
        talk.nobody_can_be_told("dead-letter watch")
        return len(rows)

    _watermark = max(int(row.get("id", _watermark)) for row in rows)
    _stranded = 0
    log.warning(
        "reported %d dead-lettered page(s) via %s: %s",
        len(rows),
        ", ".join(accepted),
        ", ".join(names),
    )
    return len(rows)
