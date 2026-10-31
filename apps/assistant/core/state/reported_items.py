"""`reported_items` table, what the brief has already told the person.

"Do not repeat yourself" as prompt text is not enough: a model can open report
after report with the same claim, re-narrated in fresh words each time, when
nothing in front of it records that the item already went out and has not
changed since. This is that record.

One row per carried item. `fingerprint` is a hash of the item's MATERIAL
state, not of the sentence the assistant wrote: a worklist row's status plus the facts
of the issue it names (`told_fingerprint`), or a bundle fact's state plus its
value. A worklist row's `last_finding` is NOT one of those facts: it is prose
The assistant writes itself, and the brief may rewrite it after every ask
about one worklist item, so each rewording would read as movement and the
same question would go out again the next morning. Same fingerprint as
yesterday means nothing about the item changed, so it may not be narrated
again; it is rendered as one carried line ("still open, day 4") or not at all.
A changed fingerprint makes the item fresh again, and it may be written out in
full.

Composition is inverted around this: candidates are filtered BEFORE the LLM
call, so an unchanged item never reaches the model to be re-narrated.

ANSWERED, pinned: an item is answered when its worklist row leaves `open`
(`worklist.close_item`), or when `mark_answered` stamps it explicitly. The
first half is enforced inside the query rather than by a sweep somebody has
to remember to call: `due_for_escalation` joins the worklist, so a ledger row
whose worklist row is closed can never come back. A `worklist:` key with no
row in the worklist at all is NOT read as answered; a read that finds nothing
is not evidence of an answer, and the escalate-once rule below is
what keeps such an orphan from repeating. There is deliberately NO
inbound-chat heuristic; "the owner replied something that sounds like an answer"
is a guess, and a wrong guess here silently drops a question the person still
owes. An answer given in conversation is recorded by the door's
`record_answer` tool: the chat session that
read the reply names the item, and `mark_answered` stamps the key whether or
not a telling was ever counted under it. `answered_keys` is what
`message_teammate` reads to refuse asking it again.

ESCALATION, pinned: once, and never on a schedule. An item is due for
escalation on the telling that takes it TO the threshold and on no other, so
an item nobody ever answers gets asked about loudly one time and then goes
quiet. Quiet is not "resolved": the item stays open on the worklist and keeps
going out as one carried line, which is what a person can act on. The
alternative is the whole reason this module exists: a question
re-asked every weekday is noise the reader learns to skip, which is how an
item ends up answered by nobody. The counter only moves on a delivered send
(`mark_reported`), so a brief that is composed and never delivered escalates
again tomorrow instead of losing the escalation. `mark_escalated` stamps an
item that was escalated by some other route, so no brief repeats it.

Storage-grammar adapter (blueprint §2.3): the read + write callables for this
table live together here.

FAILURE POLICY: Tier-1 fail-loud, like every state adapter, a failed write
propagates. A ledger that silently loses a write would let the
repeat it exists to prevent straight back through.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

WORKLIST_KEY_PREFIX = "worklist:"

#: A finding's leading "when I looked" prefix: a full ISO date, an optional
#: clock time and zone words, up to the colon that ends it.
_READING_STAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"       # the date, which is what makes this a stamp
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"   # an optional clock time
    r"[^:]{0,40}:\s*"           # the zone words, then the colon that ends it
)


@dataclass(frozen=True)
class Candidate:
    """An item the caller is considering putting in today's brief."""

    item_key: str
    fingerprint: str


@dataclass(frozen=True)
class Carried:
    """An item already reported whose material state has not moved since.

    The caller renders this as one line and never hands it to the model."""

    item_key: str
    fingerprint: str
    days_open: int
    times_reported: int


def worklist_key(item_id: int) -> str:
    """The ledger key for a worklist row, so every caller spells it the same."""
    return f"{WORKLIST_KEY_PREFIX}{int(item_id)}"


def fingerprint_of(*parts: str) -> str:
    """Hash an item's material state into a stable short fingerprint."""
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def told_fingerprint(status: str, issue_facts: str) -> str:
    """The ledger fingerprint of a worklist item a person is being told about.

    Only facts nobody at the assistant can reword: the row's status and `issue_facts`,
    the state, comment count and ticked boxes of the issue the item names, as
    the caller read them off GitHub. A person answering on the issue moves it,
    closing the row moves it, and the assistant recording yet another sentence about it
    does not.
    """
    return fingerprint_of(str(status), str(issue_facts))


def worklist_fingerprint(status: str, last_finding: str | None) -> str:
    """Whether a worklist row's finding says something new, as a fingerprint.

    The worklist's own "has this moved" test (`worklist.record_progress`), and
    deliberately not the ledger's: what a person has been told is fingerprinted
    by `told_fingerprint`, on facts rather than on this prose.

    Patrol opens each finding it writes with the moment it looked, because the
    doctrine asks for a zone on a reported time: "2026-09-16 13:00 local
    (CEST): Issue 27 still open, 0 comments. Unchanged." Patrol runs
    three times a day, so hashing that string gives a different answer three
    times a day for an item whose own last word is "Unchanged", and a ledger
    built on it says everything is fresh and nothing is ever a repeat. That is
    the bug this ledger exists to stop, arriving through its own front door.

    So the stamp comes off and the sentence is compared. What stays material is
    everything a reader would act on: the status, and the counts, numbers and
    words of the finding itself.
    """
    return fingerprint_of(str(status), _without_reading_stamp(last_finding))


def _without_reading_stamp(finding: str | None) -> str:
    """A finding with any leading "when I looked" prefix removed.

    Conservative: it only strips a prefix that opens with a full ISO date, so a
    finding written in some other shape is compared whole rather than silently
    cut at its first colon.
    """
    text = (finding or "").strip()
    return _READING_STAMP_RE.sub("", text, count=1).strip()


def _rows_for(keys: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The ledger rows for these keys, by key. Missing keys are simply absent."""
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT item_key, fingerprint, first_reported_at, last_reported_at, "
            "times_reported, answered_at, escalated_at FROM reported_items "
            f"WHERE item_key IN ({placeholders})",
            tuple(keys),
        ).fetchall()
    return {str(row["item_key"]): dict(row) for row in rows}


def _days_since(stamp: str) -> int:
    """Whole days between an ISO timestamp and now, floored at 0."""
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - then).days)


def split_candidates(
    candidates: Sequence[Candidate],
) -> tuple[list[Candidate], list[Carried]]:
    """Split today's candidates into (fresh_or_changed, carried_unchanged).

    Fresh means never reported, or reported with a different fingerprint.
    Carried means reported before with exactly this fingerprint, so nothing
    material moved and it may not be narrated again. Every candidate lands in
    exactly one of the two lists, in the order given. Read-only: this writes
    nothing, so a brief that fails to send does not mark anything as told."""
    rows = _rows_for([candidate.item_key for candidate in candidates])
    fresh: list[Candidate] = []
    carried: list[Carried] = []
    for candidate in candidates:
        row = rows.get(candidate.item_key)
        if row is None or str(row["fingerprint"]) != candidate.fingerprint:
            fresh.append(candidate)
            continue
        carried.append(
            Carried(
                item_key=candidate.item_key,
                fingerprint=candidate.fingerprint,
                days_open=_days_since(str(row["first_reported_at"])),
                times_reported=int(row["times_reported"]),
            )
        )
    return fresh, carried


def _key_and_fingerprint(item: Any) -> tuple[str, str]:
    """Read (item_key, fingerprint) off a Candidate, a Carried, or a bare key.

    A bare key carries no fingerprint, which the upsert reads as "keep the one
    already stored", the right thing when re-marking a carried item."""
    if isinstance(item, str):
        return item, ""
    return str(item.item_key), str(getattr(item, "fingerprint", "") or "")


def mark_reported(items: Sequence[Any]) -> None:
    """Record that these items went out, once per key.

    `items` are `Candidate`s (or `Carried`s, or bare keys). Called only AFTER
    a delivered send: marking on compose would let a failed send silence
    tomorrow's brief. The reported fingerprint is stored with the row, so a
    later change in the item's material state reads as fresh again."""
    pairs = {key: fingerprint for key, fingerprint in map(_key_and_fingerprint, items)}
    if not pairs:
        return
    now = utcnow_iso()
    with get_connection() as conn:
        for key, fingerprint in pairs.items():
            conn.execute(
                "INSERT INTO reported_items (item_key, fingerprint, "
                "first_reported_at, last_reported_at, times_reported) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(item_key) DO UPDATE SET "
                "fingerprint = COALESCE(NULLIF(excluded.fingerprint, ''), "
                "reported_items.fingerprint), "
                "last_reported_at = excluded.last_reported_at, "
                "times_reported = reported_items.times_reported + 1",
                (key, fingerprint, now, now),
            )
        conn.commit()


def reader_key(item_id: int, owner: str, reader: str) -> str:
    """The ledger key for telling `reader` about worklist item `item_id`.

    A person's own item is one key whoever reads it. An item the assistant owns has no
    single reader, so each reader gets their own key and telling the owner never
    counts as having told a teammate.
    """
    key = worklist_key(item_id)
    if str(owner or "").strip().lower() == "assistant":
        return f"{key}@{str(reader).strip().lower()}"
    return key


def tellings(keys: Sequence[str]) -> dict[str, tuple[str, int]]:
    """When each of these keys was last told in a delivered send, and how often.

    Keys never told are absent, and so is a row only `mark_answered` wrote
    (`times_reported` 0): an answer is not a telling. This is what the worklist
    shows beside each item, so whether a person was told is read off the
    ledger and never off a note the assistant wrote about itself.
    """
    return {
        key: (str(row["last_reported_at"]), int(row["times_reported"]))
        for key, row in _rows_for(list(keys)).items()
        if int(row["times_reported"] or 0) > 0
    }


def mark_answered(item_key: str) -> None:
    """Record that the person answered this item, so it stops escalating and
    is not asked again.

    An upsert: an answer can arrive for a key no counted telling ever wrote
    (the question went out from the chat session itself, or before this
    ledger had a caller), and an UPDATE alone would then record nothing while
    reporting success. The first answer's time is kept.
    """
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO reported_items (item_key, fingerprint, "
            "first_reported_at, last_reported_at, times_reported, answered_at) "
            "VALUES (?, '', ?, ?, 0, ?) "
            "ON CONFLICT(item_key) DO UPDATE SET answered_at = "
            "COALESCE(reported_items.answered_at, excluded.answered_at)",
            (item_key, now, now, now),
        )
        conn.commit()


def answered_keys(keys: Sequence[str]) -> set[str]:
    """Which of these ledger keys carry an answer."""
    return {
        key for key, row in _rows_for(list(keys)).items() if row["answered_at"]
    }


def due_for_escalation(threshold: int = 3) -> list[dict[str, Any]]:
    """The unanswered items whose telling count has just reached `threshold`,
    oldest first. An item nobody answers has to get louder once, not daily.

    Read-only, and once by construction: the count moves only on a delivered
    send, and the match is on the threshold telling exactly, so the same item
    cannot come back tomorrow with nothing having changed. The worklist join
    is the other half: an item whose worklist row is no longer open is
    answered and is never due, whether or not anything stamped `answered_at`.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT item_key, fingerprint, first_reported_at, last_reported_at, "
            "times_reported FROM reported_items WHERE answered_at IS NULL "
            "AND escalated_at IS NULL AND times_reported = ? "
            "AND item_key NOT IN "
            "(SELECT ? || id FROM worklist WHERE status <> 'open') "
            "ORDER BY first_reported_at ASC, item_key ASC",
            (int(threshold), WORKLIST_KEY_PREFIX),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_escalated(item_key: str) -> None:
    """Record that this item was escalated, so it escalates once, not daily."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE reported_items SET escalated_at = ? "
            "WHERE item_key = ? AND escalated_at IS NULL",
            (utcnow_iso(), item_key),
        )
        conn.commit()
