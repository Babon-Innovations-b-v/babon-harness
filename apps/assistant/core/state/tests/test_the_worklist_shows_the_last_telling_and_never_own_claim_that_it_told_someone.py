"""The worklist shows the ledger's last telling, and never the assistant's own claim that it told someone.

WHAT IT PINS. `worklist.render`, at its public seam: each open item carries one
clause read off `reported_items` saying when its reader was last told in a
delivered send and how often, or that they never were, and a sentence in the
item's finding that claims a telling is not shown. `journal.render` drops the
same claims from the journal notes it pastes into every loop. Only a telling
to a teammate is a claim, and only its clause goes: a report to an outside
party and a deadline beside the claim stay.

WHY IT EXISTS. A note like "Already briefed the owner this morning; not
repeating", written by the brief before it sent or in a run that left the item
out, is read by every later brief, which then leaves the item out again, even
near its deadline, while the ledger may hold only one telling or none. A journal
note carrying the same claim does the same damage once it is pasted into a
prompt as something the model knows.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
fixture: the ledger row for worklist:40 was written once, at 09:01 UTC on 12
October, which is 12 Oct in local, with times_reported 1. The finding
string is shaped like the container's own, stamped 22 October 08:00. A person reading the block
must see "12 Oct" and "1x" and must not see "briefed".
"""
from __future__ import annotations

import pytest

from apps.assistant.core import journal, state

_PRINTER = "Example item: a quote from Example Printers, deadline end of October"
_FALSE_NOTE = (
    "2026-10-22 08:00: no change, printer still silent at 24 days. "
    "Already briefed Alex this morning; not repeating."
)


@pytest.fixture()
def printer(monkeypatch: pytest.MonkeyPatch, tmp_path) -> int:
    """The printer item in a database of its own, with its false note on it."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    item_id = state.worklist.add_item("watch", _PRINTER, owner="Alex")
    state.worklist.record_progress(item_id, _FALSE_NOTE)
    return item_id


def _line(item_id: int) -> str:
    return next(
        line for line in state.worklist.render().splitlines()
        if line.startswith(f"- [{item_id}]")
    )


def test_an_item_never_told_says_so(printer: int) -> None:
    """No delivered send, so the block says never, whatever the note claims."""
    line = _line(printer)
    assert "never told Alex in a send" in line, line
    assert "briefed" not in line.lower(), (
        f"the note's own claim of a telling reached the prompt: {line}"
    )
    assert "printer still silent at 24 days" in line, (
        f"the part of the finding that is a finding was dropped: {line}"
    )


def test_the_block_shows_what_the_ledger_holds(printer: int, monkeypatch) -> None:
    """One telling, on 12 October, is what the reader sees."""
    with state.conn.get_connection() as conn:
        conn.execute(
            "INSERT INTO reported_items (item_key, fingerprint, first_reported_at, "
            "last_reported_at, times_reported) VALUES (?, 'fp', ?, ?, 1)",
            (
                state.reported_items.worklist_key(printer),
                "2026-10-12T09:01:23+00:00",
                "2026-10-12T09:01:23+00:00",
            ),
        )
        conn.commit()
    line = _line(printer)
    assert "last told Alex in a send: 12 Oct" in line, line
    assert "1x" in line, line
    assert "briefed" not in line.lower(), line


def test_an_answer_alone_is_not_a_telling(printer: int) -> None:
    """record_answer writes a ledger row with no telling; it must not read as one."""
    state.reported_items.mark_answered(state.reported_items.worklist_key(printer))
    assert "never told Alex in a send" in _line(printer)


def test_a_assistant_item_is_read_against_its_reader(tmp_path, monkeypatch) -> None:
    """the assistant's own items are keyed per reader; the brief's reader is the owner."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "assistant.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", "+15550100001=Alex:founder:+15550100001")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15550100001")
    state.reset_for_tests()
    item_id = state.worklist.add_item("look_into", "Find the probe side", owner="assistant")
    state.reported_items.mark_reported([f"worklist:{item_id}@alex"])
    assert "last told Alex in a send" in _line(item_id)


def test_the_journal_does_not_carry_a_telling_either(printer: int) -> None:
    """Patrol's notes, as the journal pastes them into a prompt."""
    state.add_note("Alex already briefed on this item this morning", source="patrol")
    state.add_note(
        "Printer still silent at 24 days. Already flagged it to Alex in morning brief.",
        source="patrol",
    )
    block = journal.render()
    assert "briefed" not in block.lower() and "flagged" not in block.lower(), block
    assert "Printer still silent at 24 days." in block, block


def test_an_outside_report_and_a_deadline_beside_a_claim_stay(
    printer: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The finding keeps every clause the next loop needs."""
    monkeypatch.setenv("SIGNAL_PEOPLE", "uuid:alex-uuid=Alex:dev:+15550100001")
    state.worklist.record_progress(
        printer,
        "Reported to the hosting provider's support as ticket 12345, deadline end of October.",
    )
    assert "Reported to the hosting provider's support as ticket 12345" in _line(printer)
    state.worklist.record_progress(
        printer, "printer silent 24 days, deadline this week, already flagged to Alex."
    )
    line = _line(printer)
    assert "printer silent 24 days, deadline this week" in line, line
    assert "flagged" not in line, line
