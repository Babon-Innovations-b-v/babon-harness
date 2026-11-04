"""The worklist renders open work as work and never as not news, moves an item only on news, shows the last telling, and refuses a mute that would cover a critical alert.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Checking an item is not the same event as the item changing.

WHAT IT PINS. `worklist.record_progress`, at its public seam: a finding whose
material state matches the one already stored stamps `last_checked_at` and
leaves `last_finding` and `updated_at` alone, and returns False. A finding that
says something new moves all three and returns True.

WHY IT EXISTS. Without it the two columns collapse into one. Patrol runs
several times a day and writes a finding on every open item on every pass, and
each finding opens with the moment it looked, because the doctrine asks for a
zone on a reported time. If every finding moved the item, every open item would
read "0 days since it moved", even one unchanged for a month, and anything
asking "has this moved" would be reading a clock.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what the
two column names mean, not from what the function currently does: one records
that somebody looked, the other records that the thing changed. So a repeated
finding must move exactly one of them, and the test asserts on the stored row
rather than on the return value alone. The two findings in the first case are
real strings off the container, two hours apart in stamp and identical in meaning.

THE DANGEROUS DIRECTION IS A LOST FINDING, so the second case asserts that real
news still lands: an item that genuinely moved must overwrite the finding, or
this change would quietly drop what the assistant learned.

A look_into nobody has answered is rendered as work to do, never as not news.

WHAT IT PINS. `worklist.render`, at its public seam: an open look_into older
than a day ends in a clause asking for the next step, aged from when it was
opened, while a watch that has sat still keeps its "unchanged for N days" label.

WHY IT EXISTS. The block put "unchanged for N days, so it is not news" on every
kind of item. For a watch that is right; for a look_into it read as an
instruction to skip it. An item could sit for weeks with that label, and
another could gather reworded restatements, each of which moved
`updated_at`, so it never even got a label.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what the
two kinds mean in the module docstring: a watch is checked and reported when it
changes, a look_into is pursued until it has an answer. Five days still is past
both thresholds; a look_into opened a day ago and restated twice today has a
fresh `updated_at` but is a day open by its `created_at`.

Muting a noisy alertname must not silently mute the page under it.

WHAT IT PINS. `suppression.add_suppression`, at its public seam: a pattern that
also matches something which arrived critical inside the window raises
`CriticalUnderPattern` and writes nothing. A pattern that matches only
non-critical alerts is stored. `force=True` stores it anyway.

WHY IT EXISTS. An alertname is a rule group, not an incident, and this table
matches on the name. `ResourceHigh` is five Prometheus rules under one name,
from an info-level load observation up to the critical disk-full page. So
the obvious thing to type after a noisy week silences the page you most need:
a full filesystem, which can leave the assistant mute, is watched by one of
the five.
`recurring_alerts._recurring_subjects` already refuses to FILE an Alertmanager
subject for exactly this reason and argues it at length; nothing stopped a
person muting one by hand, which is the same mistake through the other door.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
table's own matching rule rather than from this function: `is_suppressed` asks
`? LIKE pattern`, so whatever that matches is what the mute covers. The test
builds two alerts under one name, one info and one critical, exactly the
`ResourceHigh` shape, and asks what muting the name would cover. The answer
comes from the LIKE semantics, not from reading the guard.

THE DANGEROUS DIRECTION IS A MUTE THAT DOES NOT HAPPEN, because an operator who
cannot silence a flake goes deaf a slower way. So two cases assert the mute
still lands: an ordinary flake pattern, and a deliberate `force`.

A worklist item a person asked for never tells the brief it is not news.

WHAT IT PINS. `state.worklist.render`, the block the brief and the advisor
read through `manage_worklist list`: an item owned by a person that has sat
still reads "unchanged for N days, still open", while a watch the assistant opened
itself still reads "so it is not news". Otherwise the brief could drop an
item a person asked for because its line said "not news", while the
advisor, reading the same item, tells them to chase it.
`owner` is who asked for the item, not who it waits on, so no line may claim
the item is waiting on its owner: a look_into the owner asked the assistant to carry is
The assistant's job, not the owner's.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The age is set
by hand on the row, fourteen days back, and the owner is the registry spelling
the item was filed under. Nothing is asserted about how often the brief raises
the item, only what the block says about it.

The worklist shows the ledger's last telling, and never the assistant's own claim that it told someone.

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

from apps.assistant.conftest import FROZEN_AT

import inspect


# From a finding that says the same thing does not move the item.

import pytest


from apps.assistant.core import state


_ELEVEN = (
    "2026-09-16 11:00 local time (CEST): Issue 27 still open, "
    "0 comments. Assigned to Robin, no activity. Unchanged."
)


_THIRTEEN = (
    "2026-09-16 13:00 local time (CEST): Issue 27 still open, "
    "0 comments. Assigned to Robin, no activity. Unchanged."
)


@pytest.fixture()
def item(monkeypatch: pytest.MonkeyPatch, tmp_path) -> int:
    """One open item in a database of its own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    return state.worklist.add_item("watch", "Issue 27: backup restore test", owner="Robin")


def _row(item_id: int) -> dict:
    return next(row for row in state.worklist.open_items() if row["id"] == item_id)


def _a_restamped_finding_does_not_move_the_item(item: int) -> None:
    """The churn. Two patrol passes, one meaning, one stored finding."""
    assert state.worklist.record_progress(item, _ELEVEN) is True
    after_first = _row(item)

    assert state.worklist.record_progress(item, _THIRTEEN) is False
    after_second = _row(item)

    assert after_second["last_finding"] == _ELEVEN, (
        "a re-stamped finding overwrote the stored one, so the item reads as "
        "news on every patrol pass"
    )
    assert after_second["updated_at"] == after_first["updated_at"], (
        "updated_at moved for an item that did not change, which is what made "
        "it useless as a signal"
    )


def _checking_is_still_recorded(item: int) -> None:
    """Quiet is not the same as unwatched: somebody did look."""
    state.worklist.record_progress(item, _ELEVEN)
    first = _row(item)["last_checked_at"]
    state.worklist.record_progress(item, _THIRTEEN)
    assert _row(item)["last_checked_at"] != first, (
        "the pass that found nothing new was not recorded at all, so the item "
        "looks unwatched rather than unchanged"
    )


def _the_block_says_how_long_an_item_has_sat_still(item: int) -> None:
    """The point of fixing the column: a reader can see quiet from unwatched.

    Rendered by hand at a date far enough ahead that the item is quiet, since
    the alternative is a test that waits two days.
    """
    state.worklist.record_progress(item, _ELEVEN)
    fresh = state.worklist.render()
    assert "unchanged for" not in fresh, (
        f"an item that moved just now was called stale: {fresh}"
    )
    assert state.worklist._days_still("2026-01-01T00:00:00+00:00") > 200, (
        "an old stamp did not read as old, so the line can never appear"
    )
    assert state.worklist._days_still(None) == 0, (
        "an unreadable stamp must read as quiet, not as ancient"
    )


def _real_news_still_lands(item: int) -> None:
    """The other half. A finding that says something new overwrites."""
    state.worklist.record_progress(item, _ELEVEN)
    moved = state.worklist.record_progress(
        item,
        "2026-09-16 17:00 local time (CEST): Issue 27 now has 2 "
        "comments and Robin has started.",
    )
    assert moved is True
    assert "2 comments" in _row(item)["last_finding"], (
        "a finding that genuinely moved was dropped"
    )

# From a look into nobody has answered is rendered as work to do never as not news.

import datetime as _datetime


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _backdate(item_id: int, days: int, *, also_updated: bool) -> None:
    then = (
        FROZEN_AT - _datetime.timedelta(days=days)
    ).isoformat()
    column_sql = "created_at = ?, updated_at = ?" if also_updated else "created_at = ?"
    params = (then, then, item_id) if also_updated else (then, item_id)
    with state.conn.get_connection() as conn:
        conn.execute(f"UPDATE worklist SET {column_sql} WHERE id = ?", params)
        conn.commit()


def _line(item_id: int) -> str:
    return next(
        line for line in state.worklist.render().splitlines()
        if line.startswith(f"- [{item_id}]")
    )


def _a_stalled_look_into_asks_for_the_next_step(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    watched = state.worklist.add_item("watch", "Issue 27", owner="Robin")
    _backdate(probe, 5, also_updated=True)
    _backdate(watched, 5, also_updated=True)

    probe_line = _line(probe)
    assert "not news" not in probe_line, (
        f"an unanswered look_into was labelled as something to skip: {probe_line}"
    )
    assert "take the next step" in probe_line, probe_line
    assert _line(watched).endswith("unchanged for 5 days, still open"), (
        "a quiet watch lost its label"
    )


def _restating_the_symptom_does_not_hide_it(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    _backdate(probe, 1, also_updated=False)
    state.worklist.record_progress(probe, "Blind spot persists.")
    state.worklist.record_progress(probe, "Probe side still at up 0; blind spot persists.")
    assert "take the next step" in _line(probe), (
        "a reworded restatement moved updated_at and the look_into went unlabelled"
    )


def _a_look_into_opened_today_carries_no_nudge(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    assert "take the next step" not in _line(probe)

# From a mute that would cover a critical alert is refused.

from apps.assistant.core.state import suppression


@pytest.fixture
def _own_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _arrived(name: str, severity: str) -> None:
    """One alert on the record, the only input the guard reads."""
    state.record_alert(
        fingerprint=f"{name}-{severity}",
        name=name,
        severity=severity,
        status="firing",
        decision="page",
        reason="test",
        signal_sent=True,
        dead_letter=None,
    )


def _muting_a_rule_group_that_has_paged_critical_is_refused() -> None:
    """The ResourceHigh shape: one name, an observation and a page."""
    _arrived("ResourceHigh", "info")
    _arrived("ResourceHigh", "critical")

    with pytest.raises(suppression.CriticalUnderPattern) as refused:
        suppression.add_suppression("ResourceHigh", "noisy", added_by="alex")

    assert "ResourceHigh" in str(refused.value)
    assert suppression.is_suppressed("ResourceHigh") == (False, None), (
        "the mute was written despite the refusal, so the page is gone"
    )


def _muting_a_flake_still_works() -> None:
    """The ordinary case, and the reason this guard must stay narrow."""
    _arrived("backup-freshness-probe", "warning")
    suppression.add_suppression("backup-freshness-%", "known flake")
    suppressed, reason = suppression.is_suppressed("backup-freshness-probe")
    assert suppressed and reason == "known flake"


def _force_means_the_person_meant_it() -> None:
    """A refusal that cannot be overridden is a guard that gets worked around."""
    _arrived("ResourceHigh", "critical")
    suppression.add_suppression("ResourceHigh", "really", force=True)
    assert suppression.is_suppressed("ResourceHigh")[0]


def _a_pattern_matching_nothing_is_allowed_quietly() -> None:
    """Muting ahead of a known noisy deploy must not need a ceremony."""
    suppression.add_suppression("something-that-never-fired-%", "pre-emptive")
    assert suppression.is_suppressed("something-that-never-fired-yet")[0]

# From a worklist item a person asked for never renders as not news.

from apps.assistant.core.state.conn import get_connection


_TITLES = ("Chase Example Printers", "Find out why the GPU node cost rose", "Registry tag count")


@pytest.fixture()
def lines(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, str]:
    """The rendered line of each item, by title, in a database of its own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    state.worklist.add_item("watch", _TITLES[0], owner="Alex")
    state.worklist.add_item("look_into", _TITLES[1], owner="Alex")
    state.worklist.add_item("watch", _TITLES[2], owner="assistant")
    fortnight = (
        FROZEN_AT - _datetime.timedelta(days=14)
    ).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE worklist SET updated_at = ?", (fortnight,))
        conn.commit()
    rendered = state.worklist.render().splitlines()[1:]
    return {title: next(line for line in rendered if title in line) for title in _TITLES}


def _a_watch_a_person_asked_for_is_still_open(lines: dict[str, str]) -> None:
    """the owner's quiet watch is still open, and the assistant's own quiet watch is not news."""
    assert "not news" not in lines["Chase Example Printers"]
    assert "unchanged for 14 days, still open" in lines["Chase Example Printers"]
    assert "not news" in lines["Registry tag count"]


def _a_look_into_a_person_asked_for_never_blames_them(lines: dict[str, str]) -> None:
    """A look_into the owner asked the assistant to carry is the assistant's job, never waiting on the owner."""
    line = lines["Find out why the GPU node cost rose"]
    assert "waiting on" not in line
    assert "not news" not in line

# From the worklist shows the last telling and never own claim that it told someone.

from apps.assistant.core import journal


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


def _an_item_never_told_says_so(printer: int) -> None:
    """No delivered send, so the block says never, whatever the note claims."""
    line = _line(printer)
    assert "never told Alex in a send" in line, line
    assert "briefed" not in line.lower(), (
        f"the note's own claim of a telling reached the prompt: {line}"
    )
    assert "printer still silent at 24 days" in line, (
        f"the part of the finding that is a finding was dropped: {line}"
    )


def _the_block_shows_what_the_ledger_holds(printer: int, monkeypatch) -> None:
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


def _an_answer_alone_is_not_a_telling(printer: int) -> None:
    """record_answer writes a ledger row with no telling; it must not read as one."""
    state.reported_items.mark_answered(state.reported_items.worklist_key(printer))
    assert "never told Alex in a send" in _line(printer)


def _a_assistant_item_is_read_against_its_reader(tmp_path, monkeypatch) -> None:
    """the assistant's own items are keyed per reader; the brief's reader is the owner."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "assistant.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", "+15550100001=Alex:founder:+15550100001")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15550100001")
    state.reset_for_tests()
    item_id = state.worklist.add_item("look_into", "Find the probe side", owner="assistant")
    state.reported_items.mark_reported([f"worklist:{item_id}@alex"])
    assert "last told Alex in a send" in _line(item_id)


def _the_journal_does_not_carry_a_telling_either(printer: int) -> None:
    """Patrol's notes, as the journal pastes them into a prompt."""
    state.add_note("Alex already briefed on this item this morning", source="patrol")
    state.add_note(
        "Printer still silent at 24 days. Already flagged it to Alex in morning brief.",
        source="patrol",
    )
    block = journal.render()
    assert "briefed" not in block.lower() and "flagged" not in block.lower(), block
    assert "Printer still silent at 24 days." in block, block


def _an_outside_report_and_a_deadline_beside_a_claim_stay(
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


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_restamped_finding_does_not_move_the_item),
    *_cases(_checking_is_still_recorded),
    *_cases(_the_block_says_how_long_an_item_has_sat_still),
    *_cases(_real_news_still_lands),
    *_cases(_a_stalled_look_into_asks_for_the_next_step),
    *_cases(_restating_the_symptom_does_not_hide_it),
    *_cases(_a_look_into_opened_today_carries_no_nudge),
    *_cases(_muting_a_rule_group_that_has_paged_critical_is_refused, uses=('_own_database',)),
    *_cases(_muting_a_flake_still_works, uses=('_own_database',)),
    *_cases(_force_means_the_person_meant_it, uses=('_own_database',)),
    *_cases(_a_pattern_matching_nothing_is_allowed_quietly, uses=('_own_database',)),
    *_cases(_a_watch_a_person_asked_for_is_still_open),
    *_cases(_a_look_into_a_person_asked_for_never_blames_them),
    *_cases(_an_item_never_told_says_so),
    *_cases(_the_block_shows_what_the_ledger_holds),
    *_cases(_an_answer_alone_is_not_a_telling),
    *_cases(_a_assistant_item_is_read_against_its_reader),
    *_cases(_the_journal_does_not_carry_a_telling_either),
    *_cases(_an_outside_report_and_a_deadline_beside_a_claim_stay),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_worklist_renders_open_work_as_work_never_as_not_news_moves_only_on_news_and_refuses_a_mute_over_a_critical_alert(scenario, given, uses, request):
    """The worklist renders open work as work and never as not news, moves an item only on news, shows the last telling, and refuses a mute that would cover a critical alert: every row of CASES must hold, each on the frozen clock."""
    request.getfixturevalue("frozen_clock")
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
