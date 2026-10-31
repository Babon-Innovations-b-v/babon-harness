"""Pick one watching pass and run it, keeping that pass's own exit contract.

WHY THIS FILE EXISTS. Several kinds of pass run from the server side, and
this is the single door into them, so somebody looking for "the thing that
watches the assistant" finds one place.

THE ONE THING A MERGE MUST NOT FLATTEN IS THE EXIT CODE. Each unit carries
`OnFailure=harness-notify-failure@%n.service`, so the exit code is not a detail: it is
the decision to put a message on a phone. The passes deliberately disagree
about it:

    trigger      non-zero on failure. A pass that could not be fired has to
                 leave a record. Returning 0 while the deadman flag is fresh
                 would let scans vanish leaving nothing behind but a log line.
    claim-audit  the same inversion, for a sharper reason: the report is about
                 the assistant sending too many messages nobody could check, so paging
                 it to a phone would be one more of them.
    chat-relay   zero for a pass that failed once, non-zero from the fifth
                 failed pass in a row. A container restart or a gateway restart fails a
                 pass and has its own deadman; a relay stopped for ten minutes
                 is its own fault, and the sends wait in the container meanwhile.

FAILURE POLICY: per pass, listed above. This module adds none of its own. It
decides which pass runs and returns what that pass decided.
"""
from __future__ import annotations

import logging
import sys
from typing import Callable

log = logging.getLogger("openclaw.watch")


def _trigger(argv: list[str]) -> int:
    """Fire one pod-side pass. Non-zero on failure, so OnFailure= records it."""
    from apps.assistant.watch import trigger

    if len(argv) != 1:
        log.error("usage: ... apps.assistant.watch trigger /webhook/<pass>")
        return 1
    try:
        trigger.trigger(argv[0])
    except Exception as exc:  # noqa: BLE001, exit non-zero so OnFailure pages
        log.error("openclaw trigger failed: %s", exc)
        return 1
    return 0


def _claim_audit(argv: list[str]) -> int:
    """Post the weekly claim audit. Non-zero only if it reached nobody."""
    from apps.assistant.watch.claim_audit import watch

    try:
        return watch.main()
    except Exception as exc:  # noqa: BLE001, a crash here must still be recorded
        log.error("claim audit crashed: %s", exc)
        return 1


def _chat_relay(argv: list[str]) -> int:
    """Copy outside sends into the gateway's chat session. Loud only when stuck."""
    from apps.assistant.watch import chat_relay

    return chat_relay.watch()


#: Subcommand to pass. The systemd exec lines name these words, so this table is
#: deploy interface: a key renamed here is a dead timer until the units are
#: regenerated in the same commit.
PASSES: dict[str, Callable[[list[str]], int]] = {
    "trigger": _trigger,
    "claim-audit": _claim_audit,
    "chat-relay": _chat_relay,
}


def main(argv: list[str]) -> int:
    """Run the named pass and hand back its exit code, unchanged."""
    if not argv or argv[0] not in PASSES:
        log.error(
            "usage: python -m apps.assistant.watch <%s> [args]",
            "|".join(PASSES),
        )
        return 2
    return PASSES[argv[0]](argv[1:])


if __name__ == "__main__":  # pragma: no cover - `__main__.py` is the entrypoint
    sys.exit(main(sys.argv[1:]))
