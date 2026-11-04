"""The relay hands each outside send once to its recipient's own session, as an event the model reads, naming the open items a reply could answer, and stays quiet through a pod roll but still pages when stuck.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Every relayed send is queued as a system event the model reads, because chat.inject alone is transcript-only.

WHAT IT PINS. `openclaw_watch.chat_relay.deliver`, the default way a relay pass
hands a send to the gateway, with the docker commands it runs replaced by a
recorder at its `run` seam, driven through `watch` with a stand-in feed.

WHY IT EXISTS. Upstream OpenClaw marks what `chat.inject` writes as
transcript-only and never replays it to the model. A relay that only injects
copies every page into the chat and the model never reads one, so a reply to
the newest page is answered against whatever older thread the model last
saw. The
note has to reach the model through the session's system-event queue, which
the gateway drains into the next inbound turn.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The command
shape is upstream's CLI as read from the live gateway (OpenClaw 2026.9.1,
`openclaw system event --help`): `--session-key`, `--mode next-heartbeat`,
`--text`. The note text is the relay's own `note()` of the send, which the
sibling relay test pins.

The chat relay stays quiet through a container restart and still pages when the roll or the relay is stuck.

WHAT IT PINS. `openclaw_watch.chat_relay.watch`, the pass the
`harness-assistant-chat-relay` timer runs, driven through its `fetcher` and `injector`
seams; and `fetch`, which sorts the container's answer, driven through `urlopen`,
the one network call it makes.

WHY IT EXISTS. A deploy can put the new relay unit in place minutes before
the new pod is up. Meanwhile the old pod answers 404 for the feed and the
rolling one 502, and with a plain five-failures limit the relay exits non-zero
and pages someone for a roll that is going fine.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The timer
beats every two minutes. A pod not serving the feed may fail for thirty
minutes before a page, so passes 1 to 14 exit 0 and pass 15 exits 1. Any other
failure, here an inject the gateway refuses, keeps the ten-minute limit, so
passes 1 to 4 exit 0 and pass 5 exits 1. The statuses are what a roll looks
like behind Caddy: 404 from the old pod, 502 while no pod answers; 401 (a
wrong secret) and 500 (a crash in the route) are faults, not a roll.

The relay hands each send to its recipient's own session.

WHAT IT PINS. `openclaw_watch.chat_relay.watch` with the default delivery
(`deliver`), the docker commands it runs replaced by a recorder at its `run`
seam and the container's feed by a stand-in holding one send to the owner and one to a teammate.

WHY IT EXISTS. Since the gateway keeps one session per Signal sender, a note relayed into the old shared `agent:main:main` lands where nobody
talks any more, and the reply misses its question. A
recipient who has not written since the scope changed has no session yet, and
`chat.inject` refuses that as "session not found"; holding the cursor on it
would stop the relay until that person wrote.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The key shape is
upstream's, read off the running gateway (OpenClaw 2026.9.1, 2026-10-23):
`agent:<agent>:<channel>:direct:<peer>` under "per-channel-peer", with the
Signal peer being the sender's E.164 number. The refusal text is the gateway's
`chat.inject` handler's own.

The chat relay injects each outside send once, naming recipient, time and road, and retries a failed inject.

WHAT IT PINS. `openclaw_watch.chat_relay.watch`, the pass the
`openclaw-chat-relay` timer runs, with the container's feed and the gateway's
`chat.inject` replaced by stand-ins at the two seams it takes (`fetcher`,
`injector`) and its cursor in a temporary state directory.

WHY IT EXISTS. The relay is how a reply in the gateway's chat session finds the
question the assistant asked from somewhere else. Three ways it can go wrong
quietly: a send injected twice shows the assistant its own message twice; a send skipped
after a failed inject is gone for good, because the cursor has moved past it;
and a note that does not say whose words these are, to whom and when, reads to
the model as text from nowhere.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The send was
stamped 06:00 UTC on Tuesday 6 October 2026, which is 08:00 in local under
summer time; the recipient and road are the feed's own fields. The pass
sequence is fixed by the contract: the gateway refuses the second inject once,
so pass one delivers only the first send and exits 0, pass two delivers the
second, and pass three delivers nothing.

A relayed send names the open worklist items a reply could answer, so record_answer gets its item id.

WHAT IT PINS. `core.sent_feed.sends_after`, the read behind `GET /relay/sent`,
over a temporary state DB holding one page to the owner and worklist items owned by
The owner, by the assistant and by a teammate; and `openclaw_watch.chat_relay.note`, which turns
one send of that feed into the text the gateway's chat session reads.

WHY IT EXISTS. A reply closes a question only through `record_answer`, which
needs the worklist item's id. When nothing the chat sees carries one, it is
never called: the owner's "done" to a page about an item leaves the item open,
and the next brief reads it as unchanged.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Fixed by who
owns what: the owner's item and the assistant's own are ones the owner's reply can answer, and
A teammate's is not. Seven items owned by the owner are more than a page should carry, and
the five shown are the five touched last, which are the last five added.
"""
from __future__ import annotations

import inspect


# From every relayed send is queued as a system event the model reads because chat inject alone is transcript only.

import subprocess


from collections.abc import Sequence


from apps.assistant.watch import chat_relay


_SEND = {
    "id": 4,
    "sent_at": "2026-10-14T16:04:00+00:00",
    "loop": "page",
    "road": "an alert page",
    "recipient": "Alex",
    "text": "Repo index stale: the graph index has not been rebuilt since Monday.",
}


def _fetcher(after: int) -> tuple[int, list[dict]]:
    """The container's feed: one page past `after`."""
    return 4, [_SEND] if after < 4 else []


class _Gateway:
    """Records each docker command and answers it, refusing the system event when told to."""

    def __init__(self, refuse_event: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.refuse_event = refuse_event

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        refused = self.refuse_event and "system" in argv
        return subprocess.CompletedProcess(list(argv), 1 if refused else 0, "", "")


def _events(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[4:6] == ["system", "event"]]


def _each_send_is_queued_for_the_model_and_injected_into_the_transcript(tmp_path) -> None:
    """One pass queues the note on the chat session and also injects it."""
    gateway = _Gateway()
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    events = _events(gateway.calls)
    assert len(events) == 1, f"the relay ran {gateway.calls!r}; it must queue the page as a system event once"
    event = events[0]
    assert event[event.index("--session-key") + 1] == chat_relay.session_key(_SEND)
    assert event[event.index("--mode") + 1] == "next-heartbeat", "any other mode starts a model run"
    assert event[event.index("--text") + 1] == chat_relay.note(_SEND)
    assert any("chat.inject" in call for call in gateway.calls), "the transcript copy was dropped"


def _a_refused_system_event_holds_the_cursor_so_the_send_is_retried(tmp_path) -> None:
    """A note the model could not be handed is not counted as relayed."""
    gateway = _Gateway(refuse_event=True)
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    cursor = (tmp_path / chat_relay.CURSOR_FILE).read_text().strip() if (tmp_path / chat_relay.CURSOR_FILE).exists() else "0"
    assert cursor == "0", f"the cursor moved to {cursor} past a send the model never got"

# From the chat relay stays quiet through a pod roll and still pages when the roll or the relay is stuck.

from email.message import Message


from urllib.error import HTTPError


import pytest


def _old_pod(after: int) -> tuple[int, list[dict]]:
    """The old pod of a roll: the feed route is not there yet."""
    raise chat_relay.PodNotServing(f"{chat_relay.ROUTE} answered HTTP 404")


def _one_send(after: int) -> tuple[int, list[dict]]:
    """A feed holding one page not yet relayed."""
    send = {
        "id": 1,
        "sent_at": "2026-10-07T16:00:00+00:00",
        "loop": "page",
        "road": "an alert page",
        "recipient": "Alex",
        "text": "The nightly backup did not run.",
    }
    return 1, [send] if after < 1 else []


def _a_pod_roll_pages_only_after_thirty_minutes(tmp_path) -> None:
    exits = [chat_relay.watch(tmp_path, _old_pod, lambda key, text: True) for _ in range(15)]
    assert exits == [0] * 14 + [1], (
        f"exit codes {exits}: a pod not serving the feed must page on pass 15 (30 min), not before"
    )


def _a_refused_inject_still_pages_after_ten_minutes(tmp_path) -> None:
    exits = [chat_relay.watch(tmp_path, _one_send, lambda key, text: False) for _ in range(5)]
    assert exits == [0, 0, 0, 0, 1], f"exit codes {exits}: a stuck relay must page on pass 5 (10 min)"


def _fetch_tells_a_roll_from_a_fault(monkeypatch, status: int, rolling: bool) -> None:
    def refuse(*args, **kwargs):
        raise HTTPError(chat_relay.BASE_URL, status, "refused", Message(), None)

    monkeypatch.setattr(chat_relay.urllib.request, "urlopen", refuse)
    with pytest.raises(RuntimeError) as raised:
        chat_relay.fetch("secret", 0)
    assert isinstance(raised.value, chat_relay.PodNotServing) is rolling, (
        f"HTTP {status} was sorted as {'a fault' if rolling else 'a roll'}"
    )

# From the relay hands each send to its recipients own session.

from apps.assistant.shared.name import ASSISTANT_NAME


_ALEX = "+15550100001"


_ROBIN = "+15550100017"


_SENDS = [
    {
        "id": 7, "sent_at": "2026-10-16T10:04:00+00:00", "loop": "teammate-asked",
        "road": "a message someone asked me to send", "recipient": "Alex", "address": _ALEX,
        "text": "Robin asks whether you can meet on Monday.",
    },
    {
        "id": 8, "sent_at": "2026-10-16T11:08:00+00:00", "loop": "page",
        "road": "an alert page", "recipient": "Robin", "address": _ROBIN,
        "text": "The marketing site build failed.",
    },
]


def _fetcher_3(after: int) -> tuple[int, list[dict]]:
    return 8, [send for send in _SENDS if send["id"] > after]


class _Gateway_3:
    """Records each docker command; `chat.inject` refuses the sessions named in `missing`."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self.calls: list[list[str]] = []
        self.missing = missing

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        if "chat.inject" in argv and any(key in argv[-1] for key in self.missing):
            return subprocess.CompletedProcess(list(argv), 1, "", "Error: session not found")
        return subprocess.CompletedProcess(list(argv), 0, "{}", "")


def _event_keys(calls: list[list[str]]) -> list[str]:
    return [call[call.index("--session-key") + 1] for call in calls if "--session-key" in call]


def _each_note_goes_to_the_session_of_the_person_it_was_sent_to(tmp_path) -> None:
    """the owner's note reaches the owner's session and a teammate's reaches a teammate's, never the shared one."""
    gateway = _Gateway_3()
    assert chat_relay.watch(tmp_path, _fetcher_3, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    keys = _event_keys(gateway.calls)
    assert keys == [f"agent:main:signal:direct:{_ALEX}", f"agent:main:signal:direct:{_ROBIN}"], (
        f"the relay queued notes for {keys}; each must go to its recipient's own session"
    )
    assert not any("agent:main:main" in " ".join(call) for call in gateway.calls), "a note went to the shared session"


def _a_recipient_with_no_session_yet_does_not_stop_the_relay(tmp_path) -> None:
    """A refused inject for a session that does not exist yet still moves the cursor on."""
    gateway = _Gateway_3(missing=frozenset({_ROBIN}))
    assert chat_relay.watch(tmp_path, _fetcher_3, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    assert (tmp_path / chat_relay.CURSOR_FILE).read_text().strip() == "8", (
        f"the relay stopped on a recipient who has not written to {ASSISTANT_NAME} since the scope changed"
    )

# From the relay injects each outside send once naming recipient time and road and a failed inject is retried.

_SENDS_4 = [
    {
        "id": 3,
        "sent_at": "2026-10-06T06:00:00+00:00",
        "loop": "teammate-self",
        "road": "a message nobody asked for (the brief, the advisor or my own initiative)",
        "recipient": "Alex",
        "text": "Did Jordan give the caterer's price per head? Put the number on issue 47.",
    },
    {
        "id": 5,
        "sent_at": "2026-10-06T07:30:00+00:00",
        "loop": "page",
        "road": "an alert page",
        "recipient": "Alex",
        "text": "The nightly backup did not run.",
    },
]


def _fetcher_4(after: int) -> tuple[int, list[dict]]:
    """The container's feed: newest row 9 (rows 6 to 9 are not relayable), sends past `after`."""
    return 9, [send for send in _SENDS_4 if send["id"] > after]


def _each_send_is_injected_once_and_a_refused_one_is_retried(tmp_path) -> None:
    injected: list[str] = []
    refusals = {"left": 1}

    def injector(key: str, text: str) -> bool:
        if "nightly backup" in text and refusals["left"]:
            refusals["left"] -= 1
            return False
        injected.append(text)
        return True

    for _ in range(3):
        assert chat_relay.watch(tmp_path, _fetcher_4, injector) == 0, (
            "one failed pass must not page; only five in a row may"
        )
    assert [text.endswith(send["text"]) for text, send in zip(injected, _SENDS_4)] == [True, True], (
        f"the relay injected {injected!r}; it must inject the brief, then the "
        "refused page on the next pass, each once and in order"
    )
    assert len(injected) == 2, "a send was injected twice or a refused one was dropped"


def _the_note_names_recipient_time_and_road() -> None:
    note = chat_relay.note(_SENDS_4[0])
    assert note.startswith("[Sent by me to Alex on Tue 6 Oct 08:00, from a message nobody asked for"), note
    assert "my own words" in note, "the note does not tell the model these were its own words"

# From a relayed send names the open worklist items a reply could answer so record answer gets its item id.

from apps.assistant.core import outbound, sent_feed, state


_SAM = "+15550100011"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner and a teammate in the registry and an empty state DB."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX},{_SAM}=Sam:founder:{_SAM}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    state.reset_for_tests()


def _the_note_names_the_recipients_items_and_assistants_but_not_a_teammates(registry: None) -> None:
    """The page to the owner carries the owner's and the assistant's open item ids, and the note tells the chat to record."""
    alexs = state.worklist.add_item("question", "Rotate the Anthropic key", owner="Alex")
    assistants = state.worklist.add_item("question", "catering 47: the caterer's price per head", owner="assistant")
    sams = state.worklist.add_item("question", "Sam's invoice run", owner="Sam")
    outbound.remember_sent("", "The example-api-key rotation was never recorded.")

    send = sent_feed.sends_after(0).sends[0]
    ids = {item["id"] for item in send["open_items"]}
    assert {alexs, assistants} <= ids and sams not in ids, (
        f"the page to Alex carried items {ids}; it must carry Alex's {alexs} and "
        f"{ASSISTANT_NAME}'s {assistants}, never Sam's {sams}"
    )
    note = chat_relay.note(send)
    assert f"[{alexs}]" in note and f"[{assistants}]" in note, f"the note names no item id: {note!r}"
    assert "record_answer" in note, "the note never says how a reply closes the item"


def _a_long_list_is_capped_at_the_items_touched_last(registry: None) -> None:
    """Seven open items for the owner show as the five most recently moved."""
    added = [state.worklist.add_item("watch", f"watch {number}", owner="Alex") for number in range(7)]
    outbound.remember_sent("", "The nightly backup did not run.")

    shown = [item["id"] for item in sent_feed.sends_after(0).sends[0]["open_items"]]
    assert sorted(shown) == sorted(added[-5:]), f"the page carried {shown}; it must carry the last five, {added[-5:]}"


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
    *_cases(_each_send_is_queued_for_the_model_and_injected_into_the_transcript),
    *_cases(_a_refused_system_event_holds_the_cursor_so_the_send_is_retried),
    *_cases(_a_pod_roll_pages_only_after_thirty_minutes),
    *_cases(_a_refused_inject_still_pages_after_ten_minutes),
    *_cases(_fetch_tells_a_roll_from_a_fault, ("status", "rolling"), [(404, True), (502, True), (401, False), (500, False)]),
    *_cases(_each_note_goes_to_the_session_of_the_person_it_was_sent_to),
    *_cases(_a_recipient_with_no_session_yet_does_not_stop_the_relay),
    *_cases(_each_send_is_injected_once_and_a_refused_one_is_retried),
    *_cases(_the_note_names_recipient_time_and_road),
    *_cases(_the_note_names_the_recipients_items_and_assistants_but_not_a_teammates),
    *_cases(_a_long_list_is_capped_at_the_items_touched_last),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_relay_hands_each_outside_send_once_to_its_recipients_own_session_as_an_event_the_model_reads_and_stays_quiet_through_a_pod_roll(scenario, given, uses, request):
    """The relay hands each outside send once to its recipient's own session, as an event the model reads, naming the open items a reply could answer, and stays quiet through a pod roll but still pages when stuck: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
