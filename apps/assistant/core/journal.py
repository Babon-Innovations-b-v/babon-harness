"""openclaw's knowledge block, what it wrote down, fed into every loop
.

Companion to `core.principles`: principles are HOW openclaw works, the
journal is WHAT it knows. `render()` returns the memory block that chat,
triage, the notify filter, the advisor, the monitor digest and the
morning line all paste into their prompt: the newest weekly compacts
(long-term memory) followed by the recent journal notes (short-term
findings, events, per-person facts). Empty stores render to an empty
string so quiet weeks cost no prompt space.

Single public callable: `render()`.

FAILURE POLICY: Tier-2, if a read fails, render whatever half is
readable (or nothing) and log; a broken memory read must never take a
loop down with it. The writes behind it are Tier-1 in `core.state`.
"""
from __future__ import annotations

import logging

from apps.assistant.core import claims, people, state

log = logging.getLogger("openclaw.journal")

_ALL_CLEAR_PREFIXES = ("patrol clean", "stack clean", "all clear")
_TELEMETRY_MARKERS = ("stack ", "disk ", "cert ")
_TROUBLE_WORDS = (
    "down",
    "fail",
    "error",
    "stuck",
    "overdue",
    "expired",
    "crash",
    "unreachable",
    "degraded",
    "missing",
)


def _compact_lines() -> list[str]:
    compacts = state.list_compacts()
    if not compacts:
        return []
    lines = ["Earlier weeks (your weekly summaries, oldest first):"]
    for compact in compacts:
        week = compact["week_start"][:10]
        lines.append(f"[week of {week}] {compact['text']}")
    return lines


def is_all_clear_note(text: str) -> bool:
    """True for a patrol all-clear note, the green-telemetry rows.

    Patrol writes "Patrol clean. Stack 36/36, disk 47.5% free, TLS cert ...
    healthy" every three hours. A brief that pastes those rows starts
    narrating health it never checked. Conservative on purpose: any note
    naming trouble is kept, and only the recognised all-clear shapes drop.
    """
    lowered = text.strip().lower()
    # "nothing down" IS the all-clear phrasing, so it must not read as trouble.
    scanned = lowered.replace("nothing down", "")
    if any(word in scanned for word in _TROUBLE_WORDS):
        return False
    if lowered.startswith(_ALL_CLEAR_PREFIXES):
        return True
    markers = sum(1 for marker in _TELEMETRY_MARKERS if marker in lowered)
    return markers >= 2 and "healthy" in lowered


def _note_lines(include_all_clear: bool) -> list[str]:
    notes = state.recent_notes()
    if not include_all_clear:
        notes = [note for note in notes if not is_all_clear_note(note["text"])]
    if not notes:
        return []
    # A note's own "the owner already briefed on this item" is not shown: whether someone
    # was told is the ledger's to say, on the worklist line.
    teammates = people.names()
    lines = ["Recent journal notes (things you wrote down, oldest first):"]
    for note in notes:
        text = claims.without_told_claims(note["text"], teammates)
        if not text:
            continue
        day = note["added_at"][:10]
        who = f" (about {note['person']})" if note["person"] else ""
        lines.append(f"[{day}]{who} {text}")
    return lines


def render(*, include_all_clear: bool = True) -> str:
    """The WHAT-YOU-KNOW block for every loop's system prompt: weekly
    compacts then recent notes. Empty string when there is nothing yet.

    `include_all_clear=False` drops the patrol all-clear notes, for the beats
    that must not restate health they never checked.
    """
    lines: list[str] = []
    try:
        lines += _compact_lines()
    except Exception as exc:  # noqa: BLE001, Tier-2: memory read must not kill a loop
        log.warning("weekly-compact read failed; rendering without: %s", exc)
    try:
        if lines:
            lines.append("")
        lines += _note_lines(include_all_clear)
    except Exception as exc:  # noqa: BLE001, Tier-2: memory read must not kill a loop
        log.warning("journal read failed; rendering without: %s", exc)
    body = "\n".join(lines).strip()
    if not body:
        return ""
    return (
        "WHAT YOU KNOW, your own memory: weekly summaries plus recent "
        "journal notes. Use it; do not claim you have no memory of things "
        "written here:\n" + body
    )
