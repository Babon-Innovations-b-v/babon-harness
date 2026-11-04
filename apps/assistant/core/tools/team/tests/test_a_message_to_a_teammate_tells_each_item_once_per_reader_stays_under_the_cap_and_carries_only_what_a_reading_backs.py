"""A message to a teammate tells each worklist item once per reader, stays under the word cap, carries only what a reading backs, and reaches the relay as concerning the item it is about.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A message saying nothing is broken is refused while an alert that paged still fires.

WHAT IT PINS. `message_teammate.execute`, at its public seam, reading the real
alerts table through `state.alerts.firing_paged_names`: an all-clear draft
comes back as a "not sent:" string naming the alert, and no Signal send is
attempted, whoever the send is booked to and however long ago the page went
out. Once the alert resolves the same draft goes out, and an everyday "all
good" that says nothing about the systems goes out while it fires. And the worklist block
the brief reads, `state.worklist.render`, no longer calls a fault the assistant is
looking into "not news" because it has sat still.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The draft is
a typical all-clear brief, and the alert is one that paged shortly before
it (a made-up alert name and fingerprint). The rows are written as the webhook writes them: a firing
arrival whose page reached a phone, a later firing re-send, then a resolve.
Whether an alert still fires is read off those rows by hand: the newest
arrival is firing, and nothing resolved it.

A message citing an issue no door answer held, or carrying tool output or narration, is refused and never sent.

WHAT IT PINS. `message_teammate`, reached the way the gateway reaches it: over
the MCP door (`gates/mcp.py`), with a read made through the same door first.
The door keeps every OK answer it hands out (`outbound.remember_door_reading`),
and the send refuses a message that cites an issue number none of those
answers of the last half hour held, or that is the assistant's working rather than a
message: a pasted tool answer or "let me check ..." narration.

WHY IT EXISTS. Three shapes reach a person that are not messages: a list of
issue numbers and titles no tool returned, opening "Let me check the current
state of this service"; a status tool's answer pasted whole ("change_feed:
..."); and "Let me re-read what the tool returned before stating
that as fact." The send the gateway uses has to check for all
three itself.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. By reading the
door's answer as a person would: the `gh_issue_list` answer below lists issues
47 and 151 and nothing else, so a message about #38 cites an issue nobody
read and one about #47 cites one that was read. The narration and the dump
below are synthetic examples of the assistant's working, and a message to a person
opening "Let me check" or carrying "change_feed:" is not a message on its face.

A Signal message longer than the cap is refused, and nothing is sent.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a draft over
`MAX_MESSAGE_WORDS` comes back as a "not sent:" string, no Signal send is
attempted and no audit row is written. A draft at the cap goes out.

WHY IT EXISTS. Sentences asking a model to be brief do not bound length,
which is why this one is arithmetic. A principle such as "default to three
sentences or fewer" can be obeyed by a brief of three sentences and 125 words, because a
sentence has no length. A rule a model can satisfy while doing the thing the rule forbids is
not a rule, so the number lives here.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The cases are
built from `MAX_MESSAGE_WORDS` itself rather than from 40, so they say "at the
cap" and "one over it" whatever the number becomes: the invariant is that a
boundary exists and that crossing it refuses, not that it sits at any figure.
The refusal's own shape is the module's published contract, a plain string
starting "not sent:" that a model can act on, never an exception, because a
guard that raises turns a long message into no message.

THE DANGEROUS DIRECTION IS SILENCE, so the last case asks the other half: a
message inside the cap must still reach the send. A change that refused
everything would pass a test that only checked refusals.

A question asked again after the assistant only reworded its own finding is refused.

WHAT IT PINS. `message_teammate.execute` together with `manage_worklist`, at
their public seams: once a person has been asked about an open worklist item of
theirs, writing a new sentence on that row with `manage_worklist progress` does
not make the same ask sendable again. Only a fact from outside the assistant does: the
issue the item names gaining a comment or a ticked box, or the row closing.

WHY IT EXISTS. An ask repeated morning after morning is the shape this
stops. Each morning's brief can send the ask and then record a fresh
paraphrase on the row ("the owner met Jordan, no update posted"), as actor
the owner, through the door. A ledger that fingerprints that
paraphrase reads the next morning as news.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what a
person would see: nothing about the item changed between the asks except words
the assistant wrote about it, so a colleague would ask once and wait. The sequence is
an ask followed by the brief's own progress note, five times, so
one message goes out and four are refused. Then the owner comments on the issue,
which is an answer, and the next ask is a new one.

A send that lists a worklist item is counted as a telling of it, even when it names no issue number.

WHAT IT PINS. `message_teammate.execute`, at its public seam: an id passed in
`worklist_items` makes that open item one the message is about, so a delivered
send moves the ledger's count for it exactly as an issue number in the text
would.

WHY IT EXISTS. A chase message can name a vendor such as "Example Printers"
and no issue number. The ledger only matched on issue numbers, so such a
telling was never counted: an item read as told once while the owner had been
told twice, and the escalation threshold could never be reached.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule that a delivered send counts once per item it is
about: one prior telling under a different fingerprint, plus this send, is 2.
The message text is a short advisor chase, under the word cap.

A worklist item named by its bare issue number is still recognised as already told.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a message that
names one of the reader's open worklist items as "catering 47", with no "#" and no
"issue", counts as a telling of that item exactly like "#47" does, so a second
telling with nothing moved is refused.

WHY IT EXISTS. People name an issue by its bare number as often as with a
"#". A matcher that only knows "#47" and "issue 47" misses a message that
writes "catering 47", so the same ask goes out again with nothing moved.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule, "same fingerprint as yesterday may not be narrated
again", and from reading the message as a person would: "catering 47" names the
item whose title is "Issue 47 catering: ...". The two message texts are two
wordings of one ask. The other half is that a number inside
an amount ("EUR 1.500") is not an issue number, so it must not match an item
whose issue happens to be 132.

A worklist item the reader has been told, and that has not moved, is refused.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a message naming
an issue number that belongs to an OPEN worklist item this person owns is sent
once, recorded in `reported_items`, and refused the second time while the item's
material state is unchanged. The issue moving (a comment) makes it sayable again.

WHY IT EXISTS. `state/reported_items.py` was written for exactly this. Without
a caller nothing counts a repeat, and one item can reach a person on
consecutive mornings in the same words.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's own published rule rather than from this caller: "same fingerprint as
yesterday means nothing about the item changed, so it may not be narrated
again", where the fingerprint is the item's status plus the facts of its issue. So the first telling goes, the second with nothing moved does not, and
a telling after the issue gains a comment goes again. Each case asserts what a person would observe, a
message sent or a refusal, never an internal.

THE DANGEROUS DIRECTION IS SILENCE, so three of the five cases ask the other
half: a first telling goes, a moved item goes again, and an item belonging to
somebody else is not this reader's repeat. A guard that refused everything
would pass a test that only counted refusals.

An item the assistant booked to itself is still told once per reader.

WHAT IT PINS. `message_teammate.execute` with `manage_worklist`, at their public
seams: a worklist item opened under the assistant's own name (owner "assistant", which is
what the door books since `requested_by: "the assistant"` was accepted) counts in the
already-told ledger for whoever is told about it. The second unmoved telling to
the same person is refused, and telling one person does not silence the
telling to another.

WHY IT EXISTS. The ledger matched only items the RECIPIENT owns. While the
door held humans only, the brief booked everything to the owner, so the catering
question was the owner's and was matched. Once the door let the
brief book what nobody asked for to the assistant, every such item would have had
owner "assistant", and every ask about it would have skipped the ledger and been sent again
unchanged.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule ("same fingerprint as yesterday may not be narrated
again") and from what a person would see: the owner asked the same unchanged
question twice gets it once; a teammate, never told, gets it the first time.

A teammate message about a worklist item reaches the relay as concerning that item.

WHAT IT PINS. `message_teammate.execute` with `worklist_items`, then
`core.sent_feed.sends_after`, the read behind `GET /relay/sent`, and
`openclaw_watch.chat_relay.note`, which turns one send into the text the
gateway's chat session reads. All over a temporary state DB.

WHY IT EXISTS. A reply closes a question only through `record_answer`, which
needs the worklist item's id. Handing the chat the recipient's whole open
list leaves it to guess which item a reply answers, and a guess it does not
make means `record_answer` is not called. So a send that knows its item says so.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The caller
names the item, so the item is known before anything runs: the message lists
The owner's key-rotation item, and the owner's other open item is not what it is about.
The note must name the one item and the record_answer call for it, and must
not hand over the list.
"""
from __future__ import annotations

from apps.assistant.conftest import FROZEN_AT

import inspect


# From a brief cannot say nothing is broken while a page it sent is still firing.

import datetime as _datetime


from typing import Any


import pytest


from apps.assistant.core import state


from apps.assistant.core.state.conn import get_connection


from apps.assistant.core.tools.team import message_teammate


_BRIEF = (
    "Morning Alex. Nothing new for you today: everything up, deploy current, "
    "no calendar, no new issues, nothing broke overnight."
)


_FINGERPRINT = "359780fbd4f9c53c"


def _ago(**delta: float) -> str:
    return (FROZEN_AT - _datetime.timedelta(**delta)).isoformat()


def _arrival(received_at: str, status: str, *, paged: bool) -> None:
    """One webhook arrival on the alert, written as `gates/app` writes it."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts (received_at, fingerprint, name, severity, status, "
            "decision, reason, signal_sent_at, dead_letter) "
            "VALUES (?, ?, 'TargetDown', 'warning', ?, ?, '', ?, 0)",
            (received_at, _FINGERPRINT, status, "page" if paged else "silent",
             received_at if paged else None),
        )
        conn.commit()


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[tuple[str, str, str]]:
    """Every Signal send this module attempts, recorded instead of sent, over a
    state database of the test's own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[tuple[str, str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((subject, message, recipient))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


def _an_all_clear_is_refused_while_a_page_from_days_ago_still_fires(
    sent: list[Any], actor: str
) -> None:
    """Paged three days ago, re-sent firing since, never resolved."""
    _arrival(_ago(days=3), "firing", paged=True)
    _arrival(_ago(hours=1), "firing", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": _BRIEF}, actor=actor)

    assert answer.startswith("not sent:"), f"an all-clear went out over a firing page: {answer!r}"
    assert "TargetDown" in answer
    assert sent == []


def _the_same_all_clear_goes_out_once_the_alert_resolved(sent: list[Any]) -> None:
    """The dangerous direction is silence: a fixed fault must not block the brief."""
    _arrival(_ago(hours=2), "firing", paged=True)
    _arrival(_ago(minutes=30), "resolved", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": _BRIEF}, actor="assistant")

    assert answer == "messaged Alex.", answer
    assert len(sent) == 1


def _an_everyday_all_good_goes_out_while_the_alert_fires(sent: list[Any], draft: str) -> None:
    """Only a claim about the systems is checked: an unrelated reply is not blocked."""
    _arrival(_ago(days=3), "firing", paged=True)
    _arrival(_ago(hours=1), "firing", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": draft}, actor="Alex")

    assert answer == "messaged Alex.", answer
    assert len(sent) == 1


def _a_fault_assistant_is_looking_into_never_renders_as_not_news(sent: list[Any]) -> None:
    """The worklist half: a still fault stays open, a still watch stays quiet."""
    fault = state.worklist.add_item("look_into", "kube-state-metrics scrape down", owner="assistant")
    watch = state.worklist.add_item("watch", "Issue 27: backup restore test", owner="assistant")
    with get_connection() as conn:
        conn.execute("UPDATE worklist SET updated_at = ?, created_at = ?", (_ago(days=3), _ago(days=3)))
        conn.commit()

    lines = {
        line.split("]")[0].strip("- ["): line
        for line in state.worklist.render().splitlines()[1:]
    }

    assert "not news" not in lines[str(fault)]
    assert "take the next step" in lines[str(fault)]
    assert "not news" in lines[str(watch)]

# From a message citing an issue no door answer or carrying tool output or is refused and never sent.

from apps.assistant.shared.name import ASSISTANT_NAME


import json


from starlette.applications import Starlette


from starlette.routing import Route


from starlette.testclient import TestClient


from apps.assistant.core import tools


from apps.assistant.gates import mcp


_BEARER = "door-test-bearer"


_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"


# The shape `gh_issue_list` answers in: number, state, title, labels, date.
_BOARD = (
    "47\tOPEN\tSupplier contract\tPRD, area:finance\t2026-09-28T10:00:00Z\n"
    "151\tOPEN\tDev backlog\tPRD, area:dev\t2026-07-10T09:00:00Z"
)


# Synthetic examples of the assistant narrating its work or dumping tool output.
_NARRATION_FIRST = (
    "Let me check the current state of this service and any open issues "
    "first."
)


_TOOL_DUMP = (
    "deploy: last confirmed deploy 0a0a0a0a at 10:00; components: nothing down; "
    "change_feed: 'morning' last marked at 06:00"
)


_NARRATION_SECOND = (
    "Let me re-read what the tool returned before stating that "
    "as fact."
)


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database, with every Signal send recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    state.reset_for_tests()
    sent: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    def _execute(name: str, arguments: dict) -> tools.result.ToolResult:
        return tools.result.ok(name, _BOARD)

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    monkeypatch.setattr(mcp.tools, "execute_typed", _execute)
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent


def _call(client: TestClient, tool: str, arguments: dict) -> str:
    """One `tools/call` over the door, answered as its text."""
    response = client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {_BEARER}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


def _tell_alex(client: TestClient, message: str) -> str:
    return _call(
        client,
        "message_teammate",
        {"person": "Alex", "message": message, "requested_by": "Alex"},
    )


def _an_issue_no_door_answer_held_is_refused(door) -> None:
    """an issue was never read; an issue was. Only the second goes out."""
    client, sent = door
    _call(client, "gh_issue_list", {"state": "open"})
    invented = _tell_alex(client, "#38 webhook is failing.")
    assert "not sent:" in invented and "#38" in invented, invented
    assert sent == [], "an issue no tool returned reached the phone"
    real = _tell_alex(client, "#47 is still open: the supplier contract waits on you.")
    assert "messaged Alex" in real, real
    assert len(sent) == 1


def _tool_output_and_narration_are_refused(door) -> None:
    """The three examples are the assistant's working, so none of them is sent."""
    client, sent = door
    _call(client, "gh_issue_list", {"state": "open"})
    for draft in (_NARRATION_FIRST, _TOOL_DUMP, _NARRATION_SECOND):
        answer = _tell_alex(client, draft)
        assert "not sent:" in answer, (draft, answer)
    assert sent == [], f"{ASSISTANT_NAME}'s working reached the phone"


def _a_message_without_numbers_or_working_still_goes(door) -> None:
    """The ordinary relay is untouched, with no read behind it at all."""
    client, sent = door
    answer = _tell_alex(client, "Sam asked me to say the 10:00 call is on. Let me know if that clashes.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1

# From a message over the word cap is refused and never sent.

@pytest.fixture()
def sent_3(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Every Signal send this module attempts, recorded instead of sent."""
    calls: list[tuple[str, str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((subject, message, recipient))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate._state, "append_chat_turn", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


def _words(count: int) -> str:
    """A draft of exactly `count` words, in the recipient's language."""
    return " ".join(["news"] * count)


def _a_draft_one_word_over_the_cap_is_refused(sent_3: list[Any]) -> None:
    """The boundary, from the wrong side."""
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS + 1)},
        actor="Alex",
    )
    assert answer.startswith("not sent:"), f"expected a refusal, got {answer!r}"
    assert sent_3 == [], "a message over the cap was sent anyway"


def _the_refusal_names_both_numbers(sent_3: list[Any]) -> None:
    """One rewrite has to be enough, so the model is told what it wrote.

    A refusal reading only "too long" costs a guess per attempt, and the loop
    has an iteration cap: a guard that needs three tries can spend the whole
    turn arguing instead of sending.
    """
    over = message_teammate.MAX_MESSAGE_WORDS + 12
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(over)}, actor="Alex"
    )
    assert str(over) in answer, f"the refusal does not say what was written: {answer!r}"
    assert str(message_teammate.MAX_MESSAGE_WORDS) in answer, (
        f"the refusal does not say what is allowed: {answer!r}"
    )


def _the_refusal_is_a_string_and_never_an_exception(sent_3: list[Any]) -> None:
    """A guard that raises turns a long report into no report at all.

    Every other check in this module returns its refusal; this one is bound by
    the same contract, because the whole reason the cap can be trusted is that
    the worst it can do is ask for a shorter draft.
    """
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS * 5)},
        actor="Alex",
    )
    assert isinstance(answer, str) and answer.startswith("not sent:")


def _a_draft_at_the_cap_still_goes_out(sent_3: list[Any]) -> None:
    """The other half. The cap bounds a message; it does not replace one."""
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS)},
        actor="Alex",
    )
    assert not answer.startswith("not sent:"), f"a draft at the cap was refused: {answer!r}"
    assert len(sent_3) == 1, f"a draft at the cap did not reach the send: {sent_3}"

# From a question asked again after assistant only reworded its own finding is refused.

from apps.assistant.core.tools.meta import manage_worklist


_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head for the team day"


_ASKS = (
    "Alex, ask Jordan what the caterer's price per head is for #47.",
    "Did Jordan give the caterer's price for issue 47 yet? Put the number on the issue.",
    "catering 47 needs your ask to Jordan.",
    "#47: the price per head is still missing.",
    "catering 47's decisive number is still unanswered.",
)


_PROGRESS_NOTES = (
    "Asked Alex to chase Jordan for the caterer's price.",
    "Still not recorded. Asked Alex twice.",
    "Alex met Jordan, no update posted.",
    "Alex met Jordan again, still no update posted.",
    "Still unanswered.",
)


@pytest.fixture()
def issue_facts(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """What GitHub says about each issue, editable by a case, never fetched."""
    facts: dict[str, str] = {"47": "OPEN|4|2/5"}
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: facts[number])
    return facts


@pytest.fixture()
def sent_4(monkeypatch: pytest.MonkeyPatch, tmp_path, issue_facts) -> list[str]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    # The sender read its worklist through the door before writing, so every
    # issue number on it is backed (the evidence check has its own test).
    monkeypatch.setattr(
        message_teammate._outbound,
        "door_readings",
        lambda window_seconds: [
            {"outcome": "ok", "excerpt": item["title"]}
            for item in state.worklist.open_items()
        ],
    )
    return calls


def _ask_then_note(item_id: int, ask: str, note: str) -> str:
    """One morning: the brief asks, then records its own note, both as the owner."""
    answer = message_teammate.execute({"person": "Alex", "message": ask}, actor="Alex")
    manage_worklist.execute(
        {"action": "progress", "item_id": item_id, "text": note}, owner="Alex"
    )
    return answer


def _five_mornings_of_rewording_send_one_ask(sent_4: list[str]) -> None:
    """Five mornings of rewording with nothing else changed send one ask."""
    item_id = state.worklist.add_item("question", _CONTRACT_TITLE, owner="Alex")
    answers = [
        _ask_then_note(item_id, ask, note) for ask, note in zip(_ASKS, _PROGRESS_NOTES)
    ]
    assert not answers[0].startswith("not sent:"), answers[0]
    refused = [answer for answer in answers[1:] if answer.startswith("not sent:")]
    assert len(refused) == 4, answers
    assert len(sent_4) == 1, sent_4


def _an_answer_on_the_issue_makes_the_ask_new(
    sent_4: list[str], issue_facts: dict[str, str]
) -> None:
    """The way back: a person commenting on the issue is a fact the assistant cannot fake."""
    item_id = state.worklist.add_item("question", _CONTRACT_TITLE, owner="Alex")
    _ask_then_note(item_id, _ASKS[0], _PROGRESS_NOTES[0])
    issue_facts["47"] = "OPEN|5|2/5"
    answer = _ask_then_note(item_id, _ASKS[1], _PROGRESS_NOTES[1])
    assert not answer.startswith("not sent:"), answer
    assert len(sent_4) == 2

# From a send that lists a worklist item is counted as a telling of it even when it names no issue number.

_PRINTER = "Issue 7: Example Printers quote for an event, deadline end of October"


_CHASE = (
    "Example Printers never answered your 28 Sep quote request. Chase them "
    "or switch printer: this week."
)


@pytest.fixture()
def sent_5(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[str]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|3|0/0")
    return calls


def _count(item_id: int) -> int:
    key = state.reported_items.worklist_key(item_id)
    return state.reported_items.tellings([key]).get(key, ("", 0))[1]


def _the_listed_item_is_counted(sent_5: list[str]) -> None:
    item_id = state.worklist.add_item("watch", _PRINTER, owner="Alex")
    state.reported_items.mark_reported(
        [state.reported_items.Candidate(f"worklist:{item_id}", "told-earlier")]
    )
    answer = message_teammate.execute(
        {"person": "Alex", "message": _CHASE, "worklist_items": [item_id]},
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer
    assert len(sent_5) == 1
    assert _count(item_id) == 2, "the chase went out and the ledger never saw it"


def _no_list_and_no_number_still_sends(sent_5: list[str]) -> None:
    """The list is optional: without it the message goes out as before."""
    item_id = state.worklist.add_item("watch", _PRINTER, owner="Alex")
    answer = message_teammate.execute(
        {"person": "Alex", "message": _CHASE, "worklist_items": ["not a number"]},
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer
    assert _count(item_id) == 0

# From a worklist item named by its bare issue number is still recognised as already told.

_CONTRACT_TITLE_6 = "Issue 47 catering: the caterer's price per head"


_FIRST_ASK = "catering 47 needs your ask to Jordan: the caterer's price per head."


_SECOND_ASK = "catering 47's decisive number is still unanswered. Ask Jordan today."


@pytest.fixture()
def sent_6(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[str]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    return calls


def _tell(message: str) -> str:
    return message_teammate.execute({"person": "Alex", "message": message}, actor="Alex")


def _a_second_catering_47_ask_is_refused(sent_6: list[str]) -> None:
    """The bug: the same ask, spelled without '#', went out again."""
    state.worklist.add_item("question", _CONTRACT_TITLE_6, owner="Alex")
    first = _tell(_FIRST_ASK)
    assert not first.startswith("not sent:"), first
    second = _tell(_SECOND_ASK)
    assert second.startswith("not sent:"), second
    assert len(sent_6) == 1, "the bare-number re-ask went out anyway"


def _a_number_inside_an_amount_is_not_an_issue(sent_6: list[str]) -> None:
    """'EUR 1.500' is money, so it is no telling of the item for issue 132."""
    state.worklist.add_item("watch", "Issue 132: unrelated", owner="Alex")
    _tell("The team day budget totals EUR 1.500 so far.")
    answer = _tell("The team day budget still totals EUR 1.500.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent_6) == 2

# From an item already told and unmoved is not told again.

@pytest.fixture()
def issue_facts_7(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """What GitHub says about each issue, editable by a case, never fetched."""
    facts: dict[str, str] = {}
    monkeypatch.setattr(
        message_teammate, "_issue_facts", lambda number: facts.get(number, "OPEN|0|0/0")
    )
    return facts


@pytest.fixture()
def sent_7(monkeypatch: pytest.MonkeyPatch, tmp_path, issue_facts_7) -> list[str]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    # The sender read its worklist through the door before writing, so every
    # issue number on it is backed (the evidence check has its own test).
    monkeypatch.setattr(
        message_teammate._outbound,
        "door_readings",
        lambda window_seconds: [
            {"outcome": "ok", "excerpt": item["title"]}
            for item in state.worklist.open_items()
        ],
    )
    return calls


def _tell_7(message: str, person: str = "Alex") -> str:
    return message_teammate.execute({"person": person, "message": message}, actor=person)


def _the_first_telling_goes_out(sent_7: list[str]) -> None:
    """Nothing is known yet, so there is nothing to repeat."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    answer = _tell_7("Issue 12 still needs your journalctl read.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent_7) == 1


def _the_second_telling_of_an_unmoved_item_is_refused(sent_7: list[str]) -> None:
    """The same sentence about an unmoved item is not sent twice."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell_7("Issue 12 still needs your journalctl read.")
    answer = _tell_7("#12 still needs your journalctl read.")
    assert answer.startswith("not sent:"), answer
    assert len(sent_7) == 1, "the repeat went out anyway"


def _an_item_that_moved_is_sayable_again(
    sent_7: list[str], issue_facts_7: dict[str, str]
) -> None:
    """The ledger records material state, not the sentence the assistant wrote."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell_7("Issue 12 still needs your journalctl read.")
    issue_facts_7["12"] = "OPEN|1|0/0"
    answer = _tell_7("#12 ran clean this morning.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent_7) == 2


def _somebody_elses_item_is_not_this_readers_repeat(sent_7: list[str]) -> None:
    """The ledger is keyed by item, not by reader, so the owner decides.

    Without this, telling the owner about a teammate's item would silence the telling
    that goes to a teammate, whose item it actually is.
    """
    state.worklist.add_item("watch", "Issue 27: backup restore test", owner="Robin")
    _tell_7("#27 is waiting on you.", person="Robin")
    answer = _tell_7("#27 is still open on Robin's side.", person="Alex")
    assert not answer.startswith("not sent:"), answer
    assert len(sent_7) == 2


def _a_patrol_restamping_its_finding_is_not_a_change(sent_7: list[str]) -> None:
    """The way this guard would have been dead on arrival.

    Patrol opens every finding with the moment it looked, because the doctrine
    asks for a zone on a reported time, and it runs three times a day. Both
    strings below are real shapes off the container, one word apart in meaning and
    two hours apart in stamp. If the stamp counts as movement, the item reads
    as fresh three times a day and nothing is ever a repeat.
    """
    item_id = state.worklist.add_item(
        "watch", "Issue 27: backup restore test", owner="Alex"
    )
    state.worklist.record_progress(
        item_id,
        "2026-09-16 11:00 local time (CEST): Issue 27 still open, "
        "0 comments. Assigned to Robin, no activity. Unchanged.",
    )
    _tell_7("#27 is still waiting on Robin.")
    state.worklist.record_progress(
        item_id,
        "2026-09-16 13:00 local time (CEST): Issue 27 still open, "
        "0 comments. Assigned to Robin, no activity. Unchanged.",
    )
    answer = _tell_7("#27 is still waiting on Robin.")
    assert answer.startswith("not sent:"), (
        "a re-stamped finding read as movement, so the ledger calls every "
        f"patrol pass fresh news: {answer}"
    )
    assert len(sent_7) == 1


def _a_message_naming_no_item_is_never_refused(sent_7: list[str]) -> None:
    """The guard reads issue numbers; ordinary messages must pass untouched."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell_7("Issue 12 still needs your journalctl read.")
    answer = _tell_7("Booked Thursday 16:00 with Sam.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent_7) == 2

# From an item assistant booked to itself is still told once per reader.

_CONTRACT_TITLE_8 = "Issue 47 catering: the caterer's price per head"


_ASK = "catering 47 needs your ask to Jordan: the caterer's price per head."


@pytest.fixture()
def sent_8(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[tuple[str, str]]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[tuple[str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((recipient, message))
        return True

    numbers = {"alex": "+15550100012", "sam": "+15550100013"}
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: numbers[p.lower()])
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|4|2/5")
    return calls


def _book_to_assistant() -> None:
    """Open the catering question the way a door write booked to the assistant does."""
    answer = manage_worklist.execute(
        {"action": "add", "kind": "question", "title": _CONTRACT_TITLE_8}, owner="assistant"
    )
    assert answer.startswith("tracking as worklist item"), answer


def _tell_8(person: str) -> str:
    return message_teammate.execute({"person": person, "message": _ASK}, actor="assistant")


def _the_second_ask_to_alex_about_a_assistant_item_is_refused(
    sent_8: list[tuple[str, str]],
) -> None:
    """The bug: the assistant's own item never reached the ledger, so the ask repeated."""
    _book_to_assistant()
    first = _tell_8("Alex")
    assert not first.startswith("not sent:"), first
    second = _tell_8("Alex")
    assert second.startswith("not sent:"), second
    assert len(sent_8) == 1, sent_8


def _telling_alex_does_not_silence_telling_sam(
    sent_8: list[tuple[str, str]],
) -> None:
    """The dangerous direction: one reader's telling must not count for another."""
    _book_to_assistant()
    _tell_8("Alex")
    answer = _tell_8("Sam")
    assert not answer.startswith("not sent:"), answer
    assert [recipient for recipient, _ in sent_8] == ["+15550100012", "+15550100013"]

# From a teammate message about a worklist item reaches the relay as concerning that item.

from apps.assistant.watch import chat_relay


from apps.assistant.core import sent_feed


_ALEX = "+15550100012"


@pytest.fixture()
def sent_9(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[str]:
    """A real state database, the owner in the registry, and Signal recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: _ALEX)
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


def _a_message_listing_its_item_reaches_the_relay_as_concerning_that_item(sent_9: list[str]) -> None:
    """The note names the listed item and the call that records a reply to it, and no list."""
    rotation = state.worklist.add_item("question", "Rotate the Anthropic key", owner="Alex")
    other = state.worklist.add_item("watch", "Nightly backup size", owner="Alex")
    answer = message_teammate.execute(
        {
            "person": "Alex",
            "message": "Did you rotate the Anthropic key yet?",
            "worklist_items": [rotation],
        },
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer

    send = sent_feed.sends_after(0).sends[0]
    assert [item["id"] for item in send["concerns"]] == [rotation], (
        f"the send concerns {send['concerns']}; it must concern item {rotation} only"
    )
    assert send["open_items"] == [], "a send that knows its item must not also hand over the list"
    note = chat_relay.note(send)
    assert f"record_answer with item_id {rotation}" in note, f"the note names no call: {note!r}"
    assert f"[{other}]" not in note, f"the note offers item {other} as well: {note!r}"


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
    *_cases(_an_all_clear_is_refused_while_a_page_from_days_ago_still_fires, "actor", ["assistant", "Alex"]),
    *_cases(_the_same_all_clear_goes_out_once_the_alert_resolved),
    *_cases(_an_everyday_all_good_goes_out_while_the_alert_fires, "draft", ["All good, I'll book it.", "Sam, the invoice is all good."]),
    *_cases(_a_fault_assistant_is_looking_into_never_renders_as_not_news),
    *_cases(_an_issue_no_door_answer_held_is_refused),
    *_cases(_tool_output_and_narration_are_refused),
    *_cases(_a_message_without_numbers_or_working_still_goes),
    *_cases(_a_draft_one_word_over_the_cap_is_refused),
    *_cases(_the_refusal_names_both_numbers),
    *_cases(_the_refusal_is_a_string_and_never_an_exception),
    *_cases(_a_draft_at_the_cap_still_goes_out),
    *_cases(_five_mornings_of_rewording_send_one_ask),
    *_cases(_an_answer_on_the_issue_makes_the_ask_new),
    *_cases(_the_listed_item_is_counted),
    *_cases(_no_list_and_no_number_still_sends),
    *_cases(_a_second_catering_47_ask_is_refused),
    *_cases(_a_number_inside_an_amount_is_not_an_issue),
    *_cases(_the_first_telling_goes_out),
    *_cases(_the_second_telling_of_an_unmoved_item_is_refused),
    *_cases(_an_item_that_moved_is_sayable_again),
    *_cases(_somebody_elses_item_is_not_this_readers_repeat),
    *_cases(_a_patrol_restamping_its_finding_is_not_a_change),
    *_cases(_a_message_naming_no_item_is_never_refused),
    *_cases(_the_second_ask_to_alex_about_a_assistant_item_is_refused),
    *_cases(_telling_alex_does_not_silence_telling_sam),
    *_cases(_a_message_listing_its_item_reaches_the_relay_as_concerning_that_item),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_message_to_a_teammate_tells_each_item_once_per_reader_stays_under_the_cap_and_carries_only_what_a_reading_backs(scenario, given, uses, request):
    """A message to a teammate tells each worklist item once per reader, stays under the word cap, carries only what a reading backs, and reaches the relay as concerning the item it is about: every row of CASES must hold, each on the frozen clock."""
    request.getfixturevalue("frozen_clock")
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
