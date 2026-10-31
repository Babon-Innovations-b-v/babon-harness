"""`worklist` table, the jobs the assistant is carrying.

This is what turns the assistant from a thing that answers into a colleague on
shift: a durable list of what it is watching or looking into, each item
owned until closed. Three shapes of item, one table:

- ``watch``:   "keep an eye on the GPU node cost": the assistant checks it each
                 rhythm pass and reports when it changes.
- ``look_into``,  "find out why signal-cli restarted": a one-off it
                 pursues until it has an answer.
- ``question``, something the assistant asked the human and is WAITING on. A
                 real worker asks and then remembers it asked, so an
                 open question is a tracked item, not a fire-and-forget
                 line that scrolls away.

`status` is 'open' or 'done'. `last_finding` is the most recent thing
The assistant learned while working the item (shown so it can report progress
without re-deriving). `owner` is who asked for it (a person key) or
'assistant' when the assistant opened it on its own initiative.

Storage-grammar adapter (blueprint §2.3): the read + write callables for
this table live together here.

FAILURE POLICY: Tier-1 fail-loud, like every state adapter, a failed
write propagates; the assistant must never silently drop a job it took on.
"""
from __future__ import annotations

import os

from apps.assistant.shared.zone import LOCAL_ZONE

import datetime as _datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

_KINDS = ("watch", "look_into", "question")


def add_item(kind: str, title: str, owner: str = "assistant", note: str = "") -> int:
    """Open a worklist item. Returns its id. `kind` in _KINDS."""
    if kind not in _KINDS:
        raise ValueError(f"unknown worklist kind: {kind!r}")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO worklist (kind, title, note, owner, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'open', ?, ?)",
            (kind, title[:200], note[:500], owner[:60], utcnow_iso(), utcnow_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)


#: How long an item must sit unchanged before the block says so. Two days, so
#: an item raised yesterday still reads as live and one nobody has touched
#: since last week says so on its own line.
_QUIET_DAYS = 2

#: How long a look_into may stay open before the block asks for the next step.
#: One day: patrol runs three times a day, so a whole day open is three passes
#: that did not get to an answer.
_LOOK_INTO_NUDGE_DAYS = 1


def _default_reader() -> str:
    """Who reads an item the assistant owns, for the ledger line. Its own
    items go to the owner in the brief, which is the only scheduled reader:
    the people registry's name for the page recipient."""
    from apps.assistant.core import people  # lazy: avoid core-init cycle

    recipient = os.environ.get("SIGNAL_RECIPIENT", "").strip()
    person = people.identify_by_number(recipient) if recipient else None
    return person.name if person else "the owner"



_LOCAL_TZ = LOCAL_ZONE


def _told_line(reader: str, telling: tuple[str, int] | None) -> str:
    """What the ledger says about telling `reader` this item, as one clause."""
    if telling is None:
        return f"; never told {reader} in a send"
    stamp, times = telling
    try:
        when = _datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return f"; last told {reader} in a send: {times}x"
    if when.tzinfo is None:
        when = when.replace(tzinfo=_datetime.timezone.utc)
    local = when.astimezone(_LOCAL_TZ)
    return f"; last told {reader} in a send: {local.day} {local:%b} (local time), {times}x"


def _days_still(updated_at: Any) -> int:
    """Whole days since the item last MOVED, floored at 0.

    Unreadable or missing reads as 0, which is the quiet answer: an item this
    cannot date is rendered exactly as it was before this line existed.
    """
    try:
        then = _datetime.datetime.fromisoformat(str(updated_at))
    except (TypeError, ValueError):
        return 0
    if then.tzinfo is None:
        then = then.replace(tzinfo=_datetime.timezone.utc)
    return max(0, (_datetime.datetime.now(_datetime.timezone.utc) - then).days)


def record_progress(item_id: int, finding: str) -> bool:
    """Attach the latest thing the assistant learned while working an item.

    Returns whether the item MOVED. A finding that says what the last one said
    stamps `last_checked_at` and nothing else, so the two columns keep the two
    meanings they were given: `last_checked_at` is when somebody looked, and
    `updated_at` is when the thing itself changed.

    They must not collapse into one. Patrol runs three times a day and records
    a finding on every item on every pass, and each finding opens with the
    moment it looked, so without this every open item would read "0 days since
    it moved", even one unchanged for a month. Everything downstream that asks "has this
    moved" was reading a clock.

    Sameness is material sameness, `reported_items`' definition, so the leading
    reading stamp is not what makes two findings differ.
    """
    from apps.assistant.core.state import reported_items

    text = finding[:500]
    now = utcnow_iso()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_finding FROM worklist WHERE id = ?", (item_id,)
        ).fetchone()
        moved = row is None or reported_items.worklist_fingerprint(
            "open", str(row["last_finding"] or "")
        ) != reported_items.worklist_fingerprint("open", text)
        if moved:
            conn.execute(
                "UPDATE worklist SET last_finding = ?, last_checked_at = ?, "
                "updated_at = ? WHERE id = ?",
                (text, now, now, item_id),
            )
        else:
            conn.execute(
                "UPDATE worklist SET last_checked_at = ? WHERE id = ?",
                (now, item_id),
            )
        conn.commit()
    return moved


def close_item(item_id: int, resolution: str = "") -> None:
    """Mark an item done (answered, resolved, or no longer worth watching)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE worklist SET status = 'done', last_finding = "
            "COALESCE(NULLIF(?, ''), last_finding), updated_at = ? WHERE id = ?",
            (resolution[:500], utcnow_iso(), item_id),
        )
        conn.commit()


def item(item_id: int) -> dict[str, Any] | None:
    """One worklist row by id, open or not, or None when no row has that id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, kind, title, owner, status, answer, answered_by, "
            "answered_at FROM worklist WHERE id = ?",
            (int(item_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def record_answer(item_id: int, answer: str, answered_by: str) -> None:
    """Store a teammate's answer on an item, so the next brief reads it.

    The row stays open: an answer is what the person said, and whether it
    settles the item is for whoever works it next. A second answer replaces
    the first, which is how a correction lands. `updated_at` moves, because an
    answer is the item changing.
    """
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE worklist SET answer = ?, answered_by = ?, answered_at = ?, "
            "updated_at = ? WHERE id = ?",
            (answer[:500], answered_by[:60], now, now, int(item_id)),
        )
        conn.commit()


def open_items(kind: str | None = None) -> list[dict[str, Any]]:
    """Every open item, oldest-first (optionally of one kind)."""
    query = (
        "SELECT id, kind, title, note, owner, last_finding, last_checked_at, "
        "created_at, updated_at, answer, answered_by FROM worklist "
        "WHERE status = 'open'"
    )
    params: tuple = ()
    if kind is not None:
        query += " AND kind = ?"
        params = (kind,)
    query += " ORDER BY created_at ASC, id ASC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _age_label(item: dict[str, Any]) -> str:
    """How long the item has gone without its answer, as the line's last clause.

    A watch that has sat still is not news: nothing happened to the thing
    watched. A look_into that has sat open is the opposite, nobody has found
    the answer, and calling it "not news" read as an instruction to skip it:
    an item could sit for weeks that way, or collect reworded restatements
    while the cause sat in an alert row. So a
    look_into is aged from when it was opened, because a reworded restatement
    moves `updated_at` and would hide it, and the clause asks for the next step.
    """
    if item["kind"] == "look_into":
        open_days = _days_still(item.get("created_at"))
        if open_days < _LOOK_INTO_NUDGE_DAYS:
            return ""
        return (
            f"; open {open_days} days with no answer: take the next step now "
            "(read one level deeper, open an issue, or tell its owner what to "
            "do) and record that step, since 'unchanged' or 'persists' is not "
            "progress; if your tools cannot move it, make it a question for its "
            "owner or close it"
        )
    # How long it has sat still, which is a real number again now that a
    # repeated finding no longer touches `updated_at`. It is the difference
    # between "nothing has happened" and "nobody has looked", and only one of
    # those is worth a reader's attention.
    still = _days_still(item.get("updated_at"))
    if still >= _QUIET_DAYS:
        return f", {_stillness(item, still)}"
    return ""


def render(*, exclude_keys: Sequence[str] = (), include_all_clear: bool = True) -> str:
    """The worklist block for a loop's prompt: what the assistant is carrying now.
    Empty string when nothing is open (so the prompt stays clean).

    `exclude_keys` are `reported_items` keys (`worklist:<id>`) the caller has
    already rendered as carried one-liners; those items are left out so the
    model cannot narrate them a second time. `include_all_clear=False` drops a
    `last_finding` that is nothing but green telemetry, so a healthy readout
    does not travel into the prompt as if it were news. Both default to
    today's behaviour exactly.
    """
    items = open_items()
    if exclude_keys:
        skip = set(exclude_keys)
        items = [item for item in items if f"worklist:{item['id']}" not in skip]
    if not items:
        return ""
    # Imported here, not at module scope: `claims` reaches the tool registry,
    # which imports this package back. A deferred import breaks that cycle.
    from apps.assistant.core import claims, people

    green_telemetry = None if include_all_clear else claims.green_telemetry
    teammates = people.names()
    from apps.assistant.core.state import reported_items

    readers = {
        item["id"]: (
            _default_reader()
            if str(item["owner"] or "assistant").strip().lower() == "assistant"
            else str(item["owner"])
        )
        for item in items
    }
    keys = {
        item["id"]: reported_items.reader_key(
            item["id"], str(item["owner"] or "assistant"), readers[item["id"]]
        )
        for item in items
    }
    told = reported_items.tellings(list(keys.values()))
    lines = ["WHAT YOU ARE CARRYING (your open worklist, keep working these,"
             " report progress, close what is done, chase answers you are owed):"]
    label = {"watch": "watching", "look_into": "looking into", "question": "asked, waiting on answer"}
    for item in items:
        line = f"- [{item['id']}] ({label.get(item['kind'], item['kind'])}) {item['title']}"
        if item["owner"] and item["owner"] != "assistant":
            line += f" (for {item['owner']})"
        # Whether someone was told is the ledger's to say (the clause below),
        # so a finding's own "already briefed the owner" is not shown.
        finding = claims.without_told_claims(str(item["last_finding"] or ""), teammates)
        if finding and green_telemetry is not None and green_telemetry(finding):
            finding = ""
        if finding:
            line += f", last: {finding}"
        line += _told_line(readers[item["id"]], told.get(keys[item["id"]]))
        if item.get("answer"):
            # Answered in conversation and recorded: say what they
            # said, so the brief can use it and does not ask it again.
            line += (
                f", ANSWERED by {item['answered_by']}: {item['answer']}"
                ", use this answer, do NOT ask again"
            )
        elif item["kind"] == "question":
            # A question is already asked and waiting, say so loudly so no
            # beat re-nags it. A PA asks once and waits.
            line += ", ALREADY ASKED, just waiting; do NOT ask again unless new info"
        line += _age_label(item)
        lines.append(line)
    return "\n".join(lines)


def _stillness(item: dict[str, Any], still: int) -> str:
    """What an item that has sat still for `still` days says about itself.

    A fault the assistant is looking into is still broken however long it has sat, so
    it never reads as "not news": a brief that leaves out a monitoring blind
    spot because its item is old has hidden the fault. An item a person asked
    for is theirs, so it is not news only to the assistant: a brief that drops a
    person's chase as "not news" leaves them to find it themselves. The line never says who the item
    waits on, because nothing in the table records that; `owner` is who asked.
    """
    owner = str(item.get("owner") or "assistant").strip().lower()
    if item["kind"] == "look_into" or owner != "assistant":
        return f"unchanged for {still} days, still open"
    return f"unchanged for {still} days, so it is not news"
