"""A status or report tool types its own failures, names the zone of every time it prints, opens its window at the previous run, shows held and dropped pages, and refuses a memory write no reading backs.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A memory write citing a sha or an issue no reading returned is refused, and the assistant's own writes are not evidence.

WHAT IT PINS. Three seams. `write_tools.dispatch` of `remember_note` and
`manage_worklist` with an actor that carries what it read: a note or finding
citing a commit sha or a "#N" none of those readings held is refused and not
stored. The MCP door (`gates/mcp.py`): an answer that only repeats what the assistant
wrote is not kept as a reading, so it cannot back the next message, while
`github_act`'s answer, which carries the number of the issue it opened, still
is, and so is `manage_worklist` "list", whose titles carry issue numbers. And `message_teammate`: a sha no door answer held is refused.

WHY IT EXISTS. A patrol run can write "Deploy at 9abc1234, up to date" into
its journal while deploy_status says fedcba987654, copying a sha from an
earlier day; every later run then reads it as fact. And
the door kept "noted: <the note>" as a reading, so a number the assistant wrote into
its own memory backed its next message.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The
deploy_status text below holds
fedcba98 as a prefix of the full sha and does not hold 9abc1234. A number that
appears only in the assistant's own write was never returned by a tool, and an issue
GitHub numbered on create was.

A page held by quiet hours shows in `my_actions` as waiting.

WHAT IT PINS. `my_actions.execute`, the door read the chat checks before saying
whether something reached it, over the two tables that hold what has not been
sent: `notify_pen` (a ping waiting for the flush) and `page_hold` (a written
page waiting for quiet hours or the morning gate). While either holds a batch
done, asking about it answers "held", and once both have let it go the answer
no longer says so.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The ping is a
nightly batch done that arrives at 22:03 and goes out at 08:00 the next
morning. Nothing was sent in between, so the only true answer
while it waits is that it is held; the test reads that off the words "held in
the pen" and "held to send", which it does not share with any sent line.

A question answered in chat and recorded is not asked again.

WHAT IT PINS. `record_answer` (served over the MCP door) with
`message_teammate`, at their public seams: once the chat session records a
teammate's answer to an open worklist item, a later `message_teammate` naming
that item to the same person is refused and never sent, even after the issue
moved; the answer is on the worklist block the brief reads; telling somebody
else is still allowed; and the tool refuses an unknown or closed item, an
answerer the registry does not hold and an empty answer, writing nothing.

WHY IT EXISTS. The assistant asks in a cron session and hears the reply in the
gateway's chat session, which reaches nothing of ours without this. An
answer that stays in a transcript lets the next brief ask the same question
again.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what a
person would see, replaying the sequence: the brief asks the owner once
(sent), the owner answers "EUR 24.50" in chat, the session records it, a comment
lands on the issue, and next morning's same ask must not reach their phone. A teammate,
never asked, may still be told.

A report's change window opens at its previous scheduled run, and a list
cut at its cap says it is cut.

WHAT IT PINS. `whats_changed.report_window_start` and `whats_changed.execute`
at the tool seam, plus `changes.digest_since` with `changes._run_gh` (its one
subprocess seam) replaced. Morning: the previous weekday 08:00 local, so
Monday reaches back to Friday. Weekly: the previous Monday 09:00. An unknown
kind is a FAILED result, never a silent 24 hours. `REPORT_SCHEDULES` matches
the gateway's two automations. A commit list longer than the cap says MORE
EXIST and does not print a bare count.

WHY IT EXISTS. A window read from a stored marker whose only writer is gone
stays frozen at an old date, and a capped list without a word about the cap
reads as complete; a report with no marker silently gets 24 hours.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The dates are
read off a calendar: 2026-10-06 is a Tuesday, 2026-10-02 a Friday, and
local is UTC+2 in early October (CEST until 25 October), so 08:00 local is
06:00Z and 09:00 local is 07:00Z. The schedule is checked against the cron
strings in `workspace/gateway_automations.json`, read as data.

A plain string in which a tool names its own failure is never typed OK.

WHAT IT PINS. `result.coerce` and `result.render`, the seam every unmigrated
tool's plain-string answer passes through on its way to the model and to the
MCP door's `isError`. A string opening "<tool name> failed" is FAILED, one
opening "<tool name> tool not configured" is UNAVAILABLE, and an OK answer
that merely mentions a failure stays OK. An empty OK answer is rendered as
"matched nothing", never as a finding that all is well.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The failure
strings are copied from the tools that emit them on main ("gh issue list
failed (rc=1): ...", "loki query failed: HTTP 502", "db_query tool not
configured (...)"), and the expected status is what each string says about
itself in plain English: the tool did not get an answer.

stack_status counts new pods apart from in-place restarts and shows the window before.

WHAT IT PINS. `stack_status.execute`, the tool's public interface, over a real
`pod_boots` table: the container-start line names new pods (rollouts or reschedules)
and in-place container restarts as two numbers, never one total called
"restarts", and it carries the previous window's numbers so a "was N" figure is
read from the answer rather than recalled.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Kubernetes
keeps a pod's name across a container restart in place and gives a replacement
pod a new one, so a pod name's first start is a new pod and every later start
of the same name is in place. The seeded history is counted by hand: this week
pods a, b, c start once each (3 new), a starts again and pod x, first seen 20
days ago, starts again (2 in place); the week before, pods d and e start once
(2 new, 0 in place).

deploy_status names the zone of every time it prints.

WHAT IT PINS. `deploy_status.execute`, at its public seam, with `gh` answered
by a stand-in that returns commit statuses the way the GitHub API does: every
time in the answer is ISO UTC ending in Z.

WHY IT EXISTS. A time printed without its zone is read as local time by
whoever reads the brief, so a deploy at 18:11 UTC would read as 18:11
local, hours off.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The stamps are
written by hand in GitHub's own UTC spelling, so the answer must hold
"2026-10-14T18:11:29Z" and "2026-10-07T16:31:50Z", and no clock time without a
zone after it.

`my_actions` lists a page held overnight with its local time, and the dropped ones too.

WHAT IT PINS. `my_actions.execute`, the door read the weekday brief takes the
night from: a page still waiting shows its subject and the minute it
arrived on the local clock, and a page held since the last brief that was
dropped as no longer news shows with its reason, so the brief can say an
outage ended overnight instead of saying nothing.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The pages are
held at 23:42 UTC and 01:10 UTC on 15/16 October 2026, times chosen by hand
and not computed by the code; local is on summer time (UTC+2) until 25
October, so they arrived at Fri 01:42 and Fri 03:10 local, written out by
hand. The fixed clock puts the brief at Friday 08:05, so the window opens at
Thursday's 08:00 and both pages are inside it.

`my_actions` shows a message the assistant sent from outside the chat, in its own words, once.

WHAT IT PINS. `my_actions.execute`, the door read tool, over the two tables
every send path writes: `chat_turns` (an `assistant` row after each delivered
Signal message, from `message_teammate`, the meeting reminder and
`core.outbound.remember_sent`) and `assistant_actions` (a `team_message` row for a
`message_teammate` send only).

WHY IT EXISTS. The gateway answers every inbound message in one chat session,
and the weekday brief runs in an isolated cron session, so that session never
saw the question a reply answers. Say the brief asks the owner whether
Jordan has sent the caterer's price per head, and the owner answers "Yes": the
chat session cannot tell which question that answers.
`my_actions` read `assistant_actions` only, so a send that left without a
`team_message` row was invisible there too.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The texts are
two sends three days apart, in the shape the container writes them. What must come back is fixed
by the sequence, not by the formatter: the later question, in its own
words and addressed to the owner by name, and the earlier catering message exactly
once, although it sits in both tables.

stack_status says the VM's docker containers are outside its count.

WHAT IT PINS. `stack_status.execute`, the tool's public interface, over a real
`component_status` table with every registry component up: the answer still
says what "ALL UP" does not cover, and names where those containers' liveness
is read instead.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
registry and the collector. `monitor/registry.py` holds the components the
sweep checks and none of them is a VM docker container, while
`infra/observability/node_textfile/collect.py` watches the compose containers
(harness-*-1 and the assistant's named ones) and exports `harness_container_up`.
So an all-up answer is true of the registry only, and an answer that does not
say so can be read as covering the containers too.
"""
from __future__ import annotations

from apps.assistant.conftest import FROZEN_AT

import inspect


# From a memory write citing a sha or issue no reading returned is refused.

from apps.assistant.shared.name import ASSISTANT_NAME


import json


import pytest


from starlette.applications import Starlette


from starlette.routing import Route


from starlette.testclient import TestClient


from apps.assistant.core import state, tools


from apps.assistant.core.state import message_evidence


from apps.assistant.core.tools import write_tools


from apps.assistant.core.tools.team import message_teammate


from apps.assistant.gates import mcp


_DEPLOY_STATUS = (
    "Live deploy: fedcba9876543210fedcba9876543210fedcba98 "
    "(last success 2026-03-10 19:24:05)"
)


_BEARER = "door-test-bearer"


_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _patrol_actor() -> write_tools.Actor:
    return write_tools.Actor(
        name="assistant", loop="patrol", evidence=lambda: [_DEPLOY_STATUS]
    )


def _journal() -> list[str]:
    return [note["text"] for note in state.recent_notes()]


def _a_stale_sha_is_not_written_into_the_journal(db: None) -> None:
    """A sha copied from an earlier day is refused."""
    answer = write_tools.dispatch(
        "remember_note",
        {"note": "Deploy at 9abc1234, up to date."},
        _patrol_actor(),
    )
    assert answer.startswith("not recorded"), answer
    assert _journal() == [], "a sha no reading held went into memory"

    stored = write_tools.dispatch(
        "remember_note", {"note": "Deploy at fedcba98, up to date."}, _patrol_actor()
    )
    assert stored.startswith("noted:"), stored
    assert _journal() == ["Deploy at fedcba98, up to date."]


def _a_worklist_finding_is_held_to_the_same_rule(db: None) -> None:
    item_id = state.worklist.add_item("watch", "Deploy health")
    answer = write_tools.dispatch(
        "manage_worklist",
        {"action": "progress", "item_id": item_id, "text": "Fixed by #4242."},
        _patrol_actor(),
    )
    assert answer.startswith("not recorded"), answer
    closed = write_tools.dispatch(
        "manage_worklist",
        {"action": "close", "item_id": item_id, "text": "Healthy at 9abc1234."},
        _patrol_actor(),
    )
    assert closed.startswith("not recorded"), closed
    assert [row["id"] for row in state.worklist.open_items()] == [item_id]


def _a_phone_number_is_not_a_sha(db: None) -> None:
    answer = write_tools.dispatch(
        "remember_note",
        {"note": "Sam's number is 5550100123.", "person": "Sam"},
        _patrol_actor(),
    )
    assert answer.startswith("noted:"), answer


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database, with every Signal send recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "door.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    state.reset_for_tests()
    sent: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    monkeypatch.setattr(
        mcp.tools, "execute_typed", lambda name, arguments: tools.result.ok(name, _DEPLOY_STATUS)
    )
    monkeypatch.setattr(
        write_tools._gh_act,
        "execute",
        lambda tool_input, actor="assistant": (
            "done: created https://github.com/owner/repo/issues/4243"
        ),
    )
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent


def _call(client: TestClient, tool: str, arguments: dict) -> str:
    response = client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {_BEARER}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


def _tell_alex(client: TestClient, message: str) -> str:
    return _call(
        client, "message_teammate",
        {"person": "Alex", "message": message, "requested_by": "Alex"},
    )


def _assistants_own_write_does_not_back_its_next_message(door) -> None:
    client, sent = door
    added = _call(
        client, "manage_worklist",
        {"action": "add", "kind": "watch", "title": "#4242 is the cause",
         "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "tracking as worklist item" in added, added
    answer = _tell_alex(client, "#4242 is the cause of the outage.")
    assert "not sent:" in answer and "#4242" in answer, answer
    assert sent == []


def _an_issue_assistant_just_filed_still_backs_its_message(door) -> None:
    client, sent = door
    filed = _call(
        client, "github_act",
        {"action": "create", "title": "Probe side down", "requested_by": "Alex"},
    )
    assert "issues/4243" in filed, filed
    answer = _tell_alex(client, "Filed as #4243, the probe side is down.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1


def _a_message_citing_a_sha_nobody_read_is_refused(door) -> None:
    client, sent = door
    _call(client, "deploy_status", {})
    stale = _tell_alex(client, "Live deploy is 9abc1234.")
    assert "not sent:" in stale and "9abc1234" in stale, stale
    fresh = _tell_alex(client, "Live deploy is fedcba98.")
    assert "messaged Alex" in fresh, fresh


def _the_worklist_read_through_the_door_backs_the_numbers_in_its_titles(door) -> None:
    """Listing the worklist is a reading, not an echo: its titles hold the
    issue numbers a brief chases (worklist item 40 names an issue)."""
    client, sent = door
    state.worklist.add_item("watch", "Printer has not answered on #38")
    listed = _call(
        client, "manage_worklist", {"action": "list", "requested_by": f"{ASSISTANT_NAME}"}
    )
    assert "#38" in listed, listed
    answer = _tell_alex(client, "#38: the printer has still not answered.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1


def _a_sha_past_the_excerpt_cut_still_backs_a_message(
    door, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whats_changed answer runs to 40 commit lines and 40 issue lines, past
    the 2,000 characters a stored excerpt keeps; its last commit still counts."""
    client, sent = door
    commits = [
        f"- 2026-10-0{day % 9 + 1}T10:00:00Z {day:04d}abcdef openclaw: line {day} "
        + "of the change feed, long enough to fill the window"
        for day in range(39)
    ]
    feed = "\n".join([*commits, "- 2026-10-01T09:00:00Z 7e3f00c1d2 secret scan: fix"])
    assert feed.index("7e3f00c1d2") > message_evidence.MAX_EXCERPT_CHARS
    monkeypatch.setattr(
        mcp.tools, "execute_typed", lambda name, arguments: tools.result.ok(name, feed)
    )
    _call(client, "whats_changed", {"report_kind": "weekly"})
    answer = _tell_alex(client, "The secret scan was fixed in 7e3f00c1d2.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1

# From a page held by quiet hours shows in as waiting.

from apps.assistant.core.tools.meta import my_actions


_DONE = "batch done [nightly], all clear"


@pytest.fixture()
def held(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The batch done held twice, once in the pen and once as a page."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    state.enqueue_ping(_DONE, "dispatched=21, completed=21, failed=0", "notify")
    state.hold_page(f"{_DONE}. At 22:03.", road="pen", subject="the night")


def _a_held_batch_done_answers_held_not_absent(held) -> None:
    answer = my_actions.execute({"about": "batch done"})

    assert not answer.startswith("no actions"), answer
    assert f"held in the pen -> {_DONE}" in answer, answer
    assert "held to send -> the night" in answer, answer


def _once_sent_it_is_no_longer_shown_as_waiting(held) -> None:
    state.mark_flushed([ping["id"] for ping in state.unflushed_pings()])
    state.mark_released([page["id"] for page in state.pending_pages()])

    answer = my_actions.execute({"about": "batch done"})

    assert "held" not in answer, answer

# From a question answered in chat and recorded is not asked again.

from apps.assistant.core.tools import gateway_surface


from apps.assistant.core.tools.meta import manage_worklist


from apps.assistant.workspace import capabilities


_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head for the team day"


_ASK = "catering 47: what is the caterer's price per head? Jordan needs it."


_PEOPLE_3 = "uuid:a=Alex:dev:+15550100012,uuid:b=Sam:dev:+15550100013"


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    """A real state database, a two-person registry, sends recorded not sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE_3)
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    state.reset_for_tests()
    sent: list[tuple[str, str]] = []
    issue = {"facts": "OPEN|4|2/5"}

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append((recipient, message))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_unread_evidence_refusal", lambda *a: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: issue["facts"])
    added = manage_worklist.execute(
        {"action": "add", "kind": "question", "title": _CONTRACT_TITLE}, owner="assistant"
    )
    item_id = int(added.split("item ")[1].split(" ")[0])
    return {"sent": sent, "issue": issue, "item_id": item_id}


def _ask(person: str) -> str:
    return message_teammate.execute({"person": person, "message": _ASK}, actor="assistant")


def _record(item_id, answer: str, answered_by: str) -> str:
    return write_tools.dispatch(
        write_tools.RECORD_ANSWER,
        {"item_id": item_id, "answer": answer, "answered_by": answered_by},
        write_tools.Actor(name="Alex", loop="chat"),
    )


def _the_catering_sequence_is_not_asked_again_after_alex_answers(world: dict) -> None:
    """Ask, the owner answers in chat and it is recorded, next morning refused."""
    first = _ask("Alex")
    assert not first.startswith("not sent:"), first
    recorded = _record(world["item_id"], "EUR 24.50", "alex")
    assert write_tools.was_success(write_tools.RECORD_ANSWER, recorded), recorded
    world["issue"]["facts"] = "OPEN|5|2/5"  # a comment landed overnight
    again = _ask("Alex")
    assert again.startswith("not sent:"), again
    assert "EUR 24.50" in again
    assert len(world["sent"]) == 1, world["sent"]


def _the_brief_still_sees_and_can_pass_on_the_answer(world: dict) -> None:
    """The answer is on the worklist block, and another reader may be told."""
    _ask("Alex")
    _record(world["item_id"], "EUR 24.50", "Alex")
    block = state.worklist.render()
    assert "EUR 24.50" in block and "Alex" in block
    told_sam = _ask("Sam")
    assert not told_sam.startswith("not sent:"), told_sam


def _a_refused_answer_writes_nothing(world: dict, item, answer, answered_by) -> None:
    """Unknown item, bad id, empty answer, a stranger: refused, nothing kept."""
    result = _record(world["item_id"] if item is None else item, answer, answered_by)
    assert result.startswith("refused:"), result
    assert state.worklist.item(world["item_id"])["answer"] is None
    assert not state.reported_items.answered_keys(
        [f"worklist:{world['item_id']}@alex", f"worklist:{world['item_id']}@jordan"]
    )


def _a_closed_item_is_refused(world: dict) -> None:
    """A closed item is not waiting on anybody."""
    state.worklist.close_item(world["item_id"], "settled on the issue")
    result = _record(world["item_id"], "EUR 24.50", "Alex")
    assert result.startswith("refused:"), result


def _the_door_serves_it_and_tells_the_chat_session(world: dict) -> None:
    """Served with `requested_by` required, and named in the capability block."""
    served = {d["name"]: d for d in gateway_surface.write_definitions()}
    schema = served[write_tools.RECORD_ANSWER]["input_schema"]
    assert gateway_surface.REQUESTER_ARGUMENT in schema["required"]
    assert write_tools.RECORD_ANSWER in capabilities.render_capabilities()

# From a report window opens at the previous scheduled run and a capped list says it is capped.

from apps.assistant.workspace import fragment


from datetime import datetime, timezone


from pathlib import Path


from apps.assistant.core import changes


from apps.assistant.core.tools.meta import result, whats_changed


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


        # Tuesday 08:00:30 local: the window opens Monday 08:00.
        # Monday 08:30 local: the window reaches back to Friday 08:00.
        # Monday 09:00:30 local: exactly one week back.
def _the_window_opens_at_the_run_before_the_latest(kind: str, now: str, expected: str) -> None:
    """Each report looks back to the scheduled run before the current one."""
    assert whats_changed.report_window_start(kind, _utc(now)) == _utc(expected)


def _an_unknown_kind_fails_instead_of_falling_back_to_a_day() -> None:
    """A kind with no schedule is an error naming the valid kinds."""
    with pytest.raises(ValueError):
        whats_changed.report_window_start("evening", _utc("2026-10-06T06:00:30Z"))
    outcome = whats_changed.execute({"report_kind": "evening"})
    assert isinstance(outcome, result.ToolResult)
    assert outcome.status == result.FAILED
    assert "morning" in outcome.error and "weekly" in outcome.error


def _the_morning_window_never_reaches_back_a_month(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the tool seam, the morning window is at most four days wide
    (Monday before 08:00 reaches Thursday 08:00), whatever is in the state DB."""
    seen: list[str] = []
    monkeypatch.setattr(changes, "digest_since", lambda since: seen.append(since) or "")
    whats_changed.execute({"report_kind": "morning"})
    width = FROZEN_AT - _utc(seen[0])
    assert 0 < width.total_seconds() <= 4 * 86400 + 3600


def _cron_fields(cron: str) -> tuple[int, int, frozenset[int]]:
    """(minute, hour, Python weekdays) from a `M H * * DOW` cron line."""
    minute, hour, _day, _month, dow = cron.split()
    days: set[int] = set()
    for part in dow.split(","):
        first, _, last = part.partition("-")
        days.update(range(int(first), int(last or first) + 1))
    # cron numbers Sunday 0 and Monday 1; Python numbers Monday 0.
    return int(minute), int(hour), frozenset((day - 1) % 7 for day in days)


def _the_schedule_matches_the_gateway_automations() -> None:
    """The constant the tool uses is the cron the gateway runs."""
    declared = fragment.render_automations()["automations"]
    by_key = {entry["declarationKey"]: entry for entry in declared}
    for kind, key in (("morning", "harness:morning-brief"), ("weekly", "harness:weekly-advisor")):
        schedule = whats_changed.REPORT_SCHEDULES[kind]
        minute, hour, weekdays = _cron_fields(by_key[key]["cron"])
        assert (schedule.minute, schedule.hour, schedule.weekdays) == (minute, hour, weekdays)
        assert schedule.zone == by_key[key]["tz"]


def _a_commit_list_past_the_cap_says_more_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forty-one commits from gh render as 40 shown and MORE EXIST, never a
    bare count of 40."""
    commit_rows = "\n".join(
        json.dumps({"sha": f"{index:010d}", "message": f"commit {index}",
                    "at": f"2026-10-0{1 + index % 5}T10:00:00Z"})
        for index in range(41)
    )

    def _gh(args: list[str]) -> tuple[int, str, str]:
        return (0, commit_rows, "") if args[0] == "api" else (0, "[]", "")

    monkeypatch.setattr(changes, "_run_gh", _gh)
    digest = changes.digest_since("2026-09-07T06:00:22Z")
    assert "MORE EXIST" in digest
    assert "Commits on main (40" not in digest
    assert digest.count("\n- ") == 40
    assert "days" in digest.splitlines()[0]

# From a tool string naming its own failure is typed never ok.

def _a_tool_string_naming_its_own_failure_is_typed_never_ok(tool, text, status) -> None:
    """The status follows what the string says about the tool itself."""
    assert result.coerce(tool, text).status == status


def _a_failure_string_renders_as_not_evidence() -> None:
    """What the model reads opens with FAILED, never OK."""
    rendered = result.render(result.coerce("gh_issue_view", "gh issue view failed (rc=1): Could not resolve to an Issue"))
    assert rendered.startswith("FAILED [gh_issue_view @ ")


def _an_empty_answer_is_not_rendered_as_a_health_statement() -> None:
    """Nothing matched says nothing about health or existence."""
    rendered = result.render(result.coerce("journal_read", ""))
    assert "genuinely" not in rendered
    assert "not a statement about health or existence" in rendered

# From counts new pods apart from in place restarts and shows the window before.

from datetime import timedelta


from apps.assistant.core.state import pod_boots


from apps.assistant.core.state.reset import reset_for_tests


from apps.assistant.core.tools.meta import stack_status


def _boot(monkeypatch, pod: str, days_ago: float) -> None:
    stamp = (FROZEN_AT - timedelta(days=days_ago)).isoformat()
    monkeypatch.setattr(pod_boots, "utcnow_iso", lambda: stamp)
    state.pod_boots.record_boot(pod)


def _counts_new_pods_apart_from_in_place_restarts_and_shows_the_window_before(
    tmp_path, monkeypatch
) -> None:
    """This week reads 3 new and 2 in place, the week before 2 new and 0 in place."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    reset_for_tests()
    try:
        _boot(monkeypatch, "openclaw-x", 20)
        _boot(monkeypatch, "openclaw-d", 12)
        _boot(monkeypatch, "openclaw-e", 9)
        _boot(monkeypatch, "openclaw-a", 6)
        _boot(monkeypatch, "openclaw-b", 5)
        _boot(monkeypatch, "openclaw-a", 4)
        _boot(monkeypatch, "openclaw-x", 3)
        _boot(monkeypatch, "openclaw-c", 1)
        answer = stack_status.execute({})
    finally:
        reset_for_tests()
    assert "(last 7d): 3 new pods, 2 in-place container restarts" in answer
    assert "the 7d before that: 2 new pods, 0 in-place container restarts" in answer
    assert "pod restarts" not in answer

# From deploy status names the zone of every time it prints.

import re


from apps.assistant.core.tools.meta import deploy_status


_STATUSES = {
    "7a7a7a7a7aaa": [
        {"context": "vm/deploy", "state": "success", "updated_at": "2026-10-14T18:11:29Z"},
        {"context": "vm/gate", "state": "success", "updated_at": "2026-10-14T18:05:00Z"},
    ],
    "fedcba9876bb": [
        {"context": "vm/boot", "state": "failure", "updated_at": "2026-10-07T16:31:50Z"},
        {"context": "vm/gate", "state": "success", "updated_at": "2026-10-07T16:20:00Z"},
    ],
}


_CLOCK_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?")


def _fake_gh(args: list[str]) -> str | None:
    path = args[1]
    if "/commits?" in path:
        return "\n".join(_STATUSES)
    sha = path.split("/commits/")[1].split("/")[0]
    return json.dumps(_STATUSES[sha])


@pytest.fixture()
def answer(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(deploy_status, "_gh", _fake_gh)
    monkeypatch.setattr(
        deploy_status, "_pending_vs_main",
        lambda sha: deploy_status.PendingVsMain("up to date with main (7a7a7a7a7a)", 0),
    )
    return deploy_status.execute({})


def _every_time_printed_carries_its_zone(answer: str) -> None:
    zones = _CLOCK_RE.findall(answer)
    assert zones, f"no time in the answer at all: {answer}"
    assert all(zones), (
        f"a time went out without its zone, which a reader takes as local: {answer}"
    )


def _the_real_stamps_are_there(answer: str) -> None:
    assert "last success 2026-10-14T18:11:29Z" in answer, answer
    assert "2026-10-07T16:31:50Z deploy_failed vm/boot" in answer, answer

# From lists a page held overnight with its local dropped ones too.

_BRIEF_RUNS = datetime(2026, 10, 16, 6, 5, tzinfo=timezone.utc)


@pytest.fixture()
def night(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """One page still held and one dropped because its alert resolved."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()

    class _FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102 - the brief's own minute
            return _BRIEF_RUNS if tz is None else _BRIEF_RUNS.astimezone(tz)

    monkeypatch.setattr(my_actions, "datetime", _FixedClock)
    state.hold_page(
        "TargetDown: signal-bridge metrics gone dark.", road="alertmanager",
        subject="TargetDown", severity="warning", now="2026-10-15T23:42:00+00:00",
    )
    dropped = state.hold_page(
        "assistant-whisper container is down.", road="alertmanager",
        subject=f"AssistantWhisperDown", severity="warning", now="2026-10-16T01:10:00+00:00",
    )
    state.mark_dropped([dropped], reason="its alert resolved at 01:20")


def _the_held_page_carries_its_local_arrival(night) -> None:
    answer = my_actions.execute({})

    assert "[Fri 01:42 local] held to send -> TargetDown" in answer, answer


def _a_page_dropped_overnight_is_listed_with_why(night) -> None:
    answer = my_actions.execute({})

    assert (
        f"[Fri 03:10 local] held, then not sent -> AssistantWhisperDown: "
        "its alert resolved at 01:20"
    ) in answer, answer

# From shows a message assistant sent from outside the in its own once.

_ALEX = "+15550100001"


_BRIEF_QUESTION = (
    "Nothing broke overnight, calendar clear. One thing: did Jordan send the caterer's "
    "price per head yesterday? It has to be EUR 24.50 or less. Put "
    "the number on issue 47."
)


_CONTRACT_ASK = (
    "Thursday 14:00 with the caterer: ask Jordan what the price per head is for the "
    "team day lunch, and whether we can book all 40 places. Under 30 places "
    "the group rate lapses (#47)."
)


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner in the registry, and two sends the way the container records them."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    state.reset_for_tests()
    # message_teammate: the audit row, then the chat turn.
    state.record_action("team_message", "signal Alex", _CONTRACT_ASK[:80], actor="Alex", detail=_CONTRACT_ASK)
    state.append_chat_turn(_ALEX, "assistant", _CONTRACT_ASK)
    # A send that wrote only the chat turn, the way remember_sent does.
    state.append_chat_turn(_ALEX, "assistant", _BRIEF_QUESTION)
    # What the owner said is not something the assistant sent.
    state.append_chat_turn(_ALEX, "user", "Yes")


def _a_question_sent_from_outside_the_chat_is_shown_in_its_own_words(sent: None) -> None:
    answer = my_actions.execute({})
    assert _BRIEF_QUESTION in answer, (
        "the brief's question is not in my_actions, so the chat session still "
        "cannot see what Alex's 'Yes' answers"
    )
    assert "-> Alex:" in answer, "the send is not addressed to Alex by name"
    assert "Yes" not in answer.replace(_BRIEF_QUESTION, ""), (
        f"an inbound message was listed as something {ASSISTANT_NAME} sent"
    )


def _a_teammate_message_in_both_tables_is_shown_once(sent: None) -> None:
    answer = my_actions.execute({"about": "alex"})
    assert answer.count("team day lunch") == 1, (
        "a message_teammate send is listed twice, once per table"
    )

# From stack status says vm containers are outside its count.

from apps.assistant.core.monitor.registry import REGISTRY


from apps.assistant.core.state.component_status import STATUS_UP


def _an_all_up_answer_says_the_vm_containers_are_not_in_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    reset_for_tests()
    try:
        for component in REGISTRY:
            state.component_status.record_check(component.name, STATUS_UP, True, "", 0)
        answer = stack_status.execute({})
    finally:
        reset_for_tests()
    assert f"ALL UP ({len(REGISTRY)} components)" in answer
    assert "harness-*-1" in answer
    assert "harness_container_up" in answer
    assert all(not component.name.startswith("harness-") for component in REGISTRY)


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
    *_cases(_a_stale_sha_is_not_written_into_the_journal),
    *_cases(_a_worklist_finding_is_held_to_the_same_rule),
    *_cases(_a_phone_number_is_not_a_sha),
    *_cases(_assistants_own_write_does_not_back_its_next_message),
    *_cases(_an_issue_assistant_just_filed_still_backs_its_message),
    *_cases(_a_message_citing_a_sha_nobody_read_is_refused),
    *_cases(_the_worklist_read_through_the_door_backs_the_numbers_in_its_titles),
    *_cases(_a_sha_past_the_excerpt_cut_still_backs_a_message),
    *_cases(_a_held_batch_done_answers_held_not_absent),
    *_cases(_once_sent_it_is_no_longer_shown_as_waiting),
    *_cases(_the_catering_sequence_is_not_asked_again_after_alex_answers),
    *_cases(_the_brief_still_sees_and_can_pass_on_the_answer),
    *_cases(_a_refused_answer_writes_nothing, 
    ("item", "answer", "answered_by"),
    [
        (9999, "EUR 24.50", "Alex"),
        ("not-a-number", "EUR 24.50", "Alex"),
        (None, "   ", "Alex"),
        (None, "EUR 24.50", "Jordan"),
    ],
),
    *_cases(_a_closed_item_is_refused),
    *_cases(_the_door_serves_it_and_tells_the_chat_session),
    *_cases(_the_window_opens_at_the_run_before_the_latest, 
    ("kind", "now", "expected"),
    [
        # Tuesday 08:00:30 local: the window opens Monday 08:00.
        ("morning", "2026-10-06T06:00:30Z", "2026-10-05T06:00:00Z"),
        # Monday 08:30 local: the window reaches back to Friday 08:00.
        ("morning", "2026-10-05T06:30:00Z", "2026-10-02T06:00:00Z"),
        # Monday 09:00:30 local: exactly one week back.
        ("weekly", "2026-10-05T07:00:30Z", "2026-09-28T07:00:00Z"),
    ],
),
    *_cases(_an_unknown_kind_fails_instead_of_falling_back_to_a_day),
    *_cases(_the_morning_window_never_reaches_back_a_month),
    *_cases(_the_schedule_matches_the_gateway_automations),
    *_cases(_a_commit_list_past_the_cap_says_more_exist),
    *_cases(_a_tool_string_naming_its_own_failure_is_typed_never_ok, 
    ("tool", "text", "status"),
    [
        ("gh_issue_list", "gh issue list failed (rc=1): HTTP 502", result.FAILED),
        ("loki_query", "loki query failed: HTTP 502, bad gateway", result.FAILED),
        ("agenda_view", "agenda_view failed: HTTP 500: oops", result.FAILED),
        ("db_query", "db_query tool not configured (OPENCLAW_DB_RO_URL unset)", result.UNAVAILABLE),
        ("deploy_status", "last deploy failed at 10:02, rolled back", result.OK),
        ("gh_issue_list", "#12 OPEN fix: gh issue list failed for Sam", result.OK),
    ],
),
    *_cases(_a_failure_string_renders_as_not_evidence),
    *_cases(_an_empty_answer_is_not_rendered_as_a_health_statement),
    *_cases(_counts_new_pods_apart_from_in_place_restarts_and_shows_the_window_before),
    *_cases(_every_time_printed_carries_its_zone),
    *_cases(_the_real_stamps_are_there),
    *_cases(_the_held_page_carries_its_local_arrival),
    *_cases(_a_page_dropped_overnight_is_listed_with_why),
    *_cases(_a_question_sent_from_outside_the_chat_is_shown_in_its_own_words),
    *_cases(_a_teammate_message_in_both_tables_is_shown_once),
    *_cases(_an_all_up_answer_says_the_vm_containers_are_not_in_it),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_status_or_report_tool_says_what_it_could_not_read_names_each_times_zone_and_shows_held_and_dropped_pages(scenario, given, uses, request):
    """A status or report tool types its own failures, names the zone of every time it prints, opens its window at the previous run, shows held and dropped pages, and refuses a memory write no reading backs: every row of CASES must hold, each on the frozen clock."""
    request.getfixturevalue("frozen_clock")
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
