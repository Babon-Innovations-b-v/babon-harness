"""`message_evidence` table adapter: what the assistant READ next to what the assistant SAID.

Storage-grammar table adapter (blueprint 2.3): the writes and the windowed
reads live together in the file named after the table.

WHY THIS TABLE EXISTS. Every message the assistant sends is durable
in `chat_turns`, and nothing it read to write that message was durable
anywhere. Both tool-using loops counted a result into a read counter and threw
the text away, and both no-tools loops discarded a typed bundle they had
already assembled. So a message could state a cause or a start time, and
there would be no way, afterwards, to ask what the readings behind that
sentence actually said. One row here holds the message and its readings together, so the
question can be asked a week later.

A ROW IS ALSO THE ONLY RECORD OF WHAT A ROAD TOOK IN. `record_input` writes a
row with no message text: the Alertmanager road's labels and annotations were
never stored anywhere, which is why a replay of a recorded night can re-decide
that road's timing but never its content. An input row is that payload, kept at
the moment it arrives. It starts from the day it ships; nothing backfills it,
and a recording older than that honestly has none. An input payload is JSON a
reader parses back, so it is bounded by its own cap and never truncated: half a
JSON object parses as nothing, which reads exactly like a payload nobody kept.

WHAT A READING IS. A JSON list of objects with `tool`, `arguments`, `outcome`,
`digest`, `chars`, `excerpt` and `at`. The `digest` is the sha256 of the WHOLE
result, so a truncated excerpt is still tied to exact bytes; the `excerpt` is
the bounded evidence a checker matches words against. Both caps below are
bounds on a row, not on the truth: a patrol pass can make several rounds of up
to 8 KiB each (`core/tools/meta/text.py`), and a state DB on a named volume is not
the place to keep all of it.

FAILURE POLICY: Tier-1 fail-loud, like every adapter in this package. The
defended swallow belongs at the call site (`core.outbound`), where the message
has already been sent and failing the caller would cost a real message to save
a record.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# One reading's excerpt, in characters. Long enough to hold a `kubectl get`
# table or a `systemctl list-timers` block whole, which is the size of the
# reading that shows a stale timestamp.
MAX_EXCERPT_CHARS = 2_000

# The whole `readings` column, in characters. A patrol pass makes up to
# PATROL_MAX_ITERATIONS rounds and the tool layer caps each result at 8 KiB, so
# without a row cap one pass could write a quarter of a megabyte.
MAX_READINGS_CHARS = 32 * 1024

# How long a row is kept. Nothing prunes `alerts` today and these rows are
# larger, so the retention rule ships with the table rather than after it.
RETENTION_DAYS = 90

# The tool name on the marker row that says readings were dropped for size. A
# silent drop would make the evidence look complete when it is not.
DROPPED_MARKER = "(dropped for size)"

# One road input's whole payload, in characters. Bigger than the excerpt cap
# above and bounded by its own number, because the two are not the same kind of
# text. A tool result is prose and a truncated excerpt is still evidence; a
# payload is a JSON object and a truncated one parses as nothing at all, so
# capping it the same way loses the whole payload and says it never existed.
# An Alertmanager alert with a long rule description dumps to about 2 KB,
# which a 2000-character prose cap would destroy. Still well inside the row cap.
MAX_INPUT_PAYLOAD_CHARS = 8 * 1024

# The outcome on an input row whose payload was too large to keep whole. It is
# recorded rather than half-stored: a reader gets no payload either way, and
# this way the row says why instead of looking like a road nobody recorded.
INPUT_TOO_LARGE = "too-large"


def record_said(
    loop: str,
    text: str,
    readings: Sequence[Mapping[str, Any]],
    recipient: str = "",
) -> int:
    """Store one released message together with the readings behind it.

    Returns the row id. `loop` is the loop that composed it (chat, patrol,
    morning, pen, triage); `recipient` is the destination key when there is
    one. Call it with the text that was actually released, after every strip.
    """
    return _insert(loop, recipient, text, _packed(readings))


def record_input(road: str, key: str, payload: Mapping[str, Any]) -> int:
    """Store what a road took IN, before anything was said about it.

    The same table, deliberately: an input is a reading, it is just one taken
    before the message exists rather than during it. The row carries no message
    text, which is what tells an input apart from a message afterwards.

    NOT through `_packed`, and that is the whole of this function's subtlety.
    `_packed` truncates an excerpt at `MAX_EXCERPT_CHARS` and appends a marker,
    which is right for a tool result and wrong for a payload: the reader parses
    this excerpt back as JSON, so a truncated one parses as nothing and the row
    reads exactly like a night the payload was never recorded on. Bounded by
    `MAX_INPUT_PAYLOAD_CHARS` instead, and a payload over that bound is recorded
    as too large rather than stored in half.
    """
    dumped = json.dumps(payload, sort_keys=True, default=str)
    too_large = len(dumped) > MAX_INPUT_PAYLOAD_CHARS
    return _insert(
        road,
        key,
        "",
        _dumped(
            [
                {
                    "tool": road,
                    "arguments": json.dumps({"key": key}, sort_keys=True),
                    "outcome": INPUT_TOO_LARGE if too_large else "ok",
                    "digest": digest_of(dumped),
                    "chars": len(dumped),
                    "excerpt": (
                        f"payload of {len(dumped)} characters, over the "
                        f"{MAX_INPUT_PAYLOAD_CHARS} character bound"
                        if too_large
                        else dumped
                    ),
                    "at": utcnow_iso(),
                }
            ]
        ),
    )


def said_between(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Every recorded MESSAGE with `start_iso <= said_at < end_iso`, oldest first.

    Input rows are left out: they carry no message, so a checker over sent text
    has nothing to check in them.
    """
    return [
        row for row in _rows_between(start_iso, end_iso) if row["text"]
    ]


def inputs_between(
    start_iso: str, end_iso: str, road: str | None = None
) -> list[dict[str, Any]]:
    """Every recorded ROAD INPUT in the window, oldest first, optionally one road.

    The mirror of `said_between`: rows with no message text, which is what a
    replay reads to re-decide an arrival it would otherwise have to report as
    unreplayable.
    """
    found = [row for row in _rows_between(start_iso, end_iso) if not row["text"]]
    if road is None:
        return found
    return [row for row in found if row["loop"] == road]


def vacuum_old(days: int = RETENTION_DAYS) -> int:
    """Delete rows older than `days`. Returns how many went.

    Readings rows are the largest thing openclaw writes, so unlike `alerts`
    this table gets its retention rule at birth rather than after somebody
    notices the state volume filling.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM message_evidence WHERE said_at < ?", (cutoff,)
        )
        conn.commit()
        return cursor.rowcount


def digest_of(result_text: str) -> str:
    """The sha256 of a whole tool result, which is a reading's identity.

    Kept here rather than at the call site because the excerpt stored beside it
    is truncated: without the digest, two different readings that share a first
    two thousand characters are indistinguishable in the row.
    """
    return hashlib.sha256(result_text.encode("utf-8", "replace")).hexdigest()


def _insert(loop: str, recipient: str, text: str, readings: str) -> int:
    """Write one row and hand back its id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO message_evidence (loop, recipient, text, readings, said_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (loop, recipient, text, readings, utcnow_iso()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _rows_between(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Every row in the window, oldest first, with `readings` already parsed."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, loop, recipient, text, readings, said_at FROM message_evidence "
            "WHERE said_at >= ? AND said_at < ? ORDER BY said_at ASC, id ASC",
            (start_iso, end_iso),
        ).fetchall()
    return [_unpacked(row) for row in rows]


def _unpacked(row: Any) -> dict[str, Any]:
    """One stored row with its readings back as a list.

    A row whose JSON will not parse comes back with no readings rather than
    taking the whole window down: the message half of the row is still true,
    and a reader that loses one row's evidence is better than one that loses
    the week.
    """
    record = dict(row)
    try:
        parsed = json.loads(record["readings"])
    except ValueError:
        parsed = []
    record["readings"] = parsed if isinstance(parsed, list) else []
    return record


def _packed(readings: Sequence[Mapping[str, Any]]) -> str:
    """The readings as the stored JSON, capped per reading and per row.

    Dropping is from the END, so the first thing a loop read survives the cap,
    and it is announced in a marker row rather than done quietly.
    """
    capped = [_capped(one) for one in readings]
    dropped = 0
    while len(capped) > 1 and len(_dumped(capped)) > MAX_READINGS_CHARS - 300:
        capped.pop()
        dropped += 1
    if dropped:
        capped.append(
            {
                "tool": DROPPED_MARKER,
                "arguments": "",
                "outcome": "dropped",
                "digest": "",
                "chars": 0,
                "excerpt": f"{dropped} further readings did not fit the row cap",
                "at": utcnow_iso(),
            }
        )
    return _dumped(capped)


def _capped(reading: Mapping[str, Any]) -> dict[str, Any]:
    """One reading with its excerpt truncated to the per-reading cap.

    Truncation is announced in the text itself, because an excerpt that stops
    mid-sentence with no marker reads as a tool that returned that much.
    """
    excerpt = str(reading.get("excerpt", ""))
    if len(excerpt) > MAX_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_EXCERPT_CHARS] + " ...(truncated)"
    return {
        "tool": str(reading.get("tool", "")),
        "arguments": str(reading.get("arguments", "")),
        "outcome": str(reading.get("outcome", "")),
        "digest": str(reading.get("digest", "")),
        "chars": int(reading.get("chars", len(excerpt))),
        "excerpt": excerpt,
        "at": str(reading.get("at", "")),
    }


def _dumped(readings: list[dict[str, Any]]) -> str:
    """The stored JSON rendering, with keys sorted so a row is byte-stable."""
    return json.dumps(readings, sort_keys=True, default=str)
