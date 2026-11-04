"""A notulen names each person once, caps the speakers, and never names a speaker the transcript does not place.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A set of minutes names each person once, and carries no more voices than there were people.

WHAT IT PINS. Two halves of one rule, on the two sides of the notulen twin.
`clean_attendees` in `app/core/sessions/attendee_list.py` is the dashboard's
public seam for an attendee list; `_voices_to_keep` and `_fold_stray_voices` in
`entrypoints/worker.py` are the GPU worker's half, which it carries by hand
because its image imports nothing from `app/`.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From a list
worked out by hand and a fold worked out by hand. `['alice', 'bob', 'Bob']`
for a meeting with two people on it is two names and two voices. The fold case
is five turns whose talk times and gaps are small enough to add up on paper:
two voices of ten seconds each and two strays of one second, each stray
touching one kept voice and sitting nine seconds from the other, so each stray
can only go one way.

WHAT IT WAS PROVED AGAINST. Sorting the voices the wrong way round, so the fold
keeps the two one-second strays and hands the real speakers to them.

GUARDS. The twin rule in `apps/notulen/CLAUDE.md`.

A set of minutes never names a speaker the transcript does not place.

WHAT IT PINS. The one paragraph of the minutes system prompt that decides
whether a `[SPEAKER_nn]` label becomes a person's name, on both sides of the
notulen twin: `_generate_notulen` in `entrypoints/worker.py` (the GPU worker)
and `generate_notulen` in `app/core/minutes/notulen_writer.py` (the CPU path).
The seam is the `system` prompt each of them hands Claude, which is the only
place either twin says who a voice belongs to.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the failure
it guards: a transcript in which neither attendee's name is ever said, so the
audio places neither of them, and a writer told to "link the speaker labels to
the attendees based on context" names both anyway, possibly the wrong way
round. So that order must not be what either writer is told, and a writer with
no evidence needs something to put in the minutes instead of a name, which is
the speaker label itself. The third case is the twin rule: the paragraph reads
the same on both sides.

WHAT IT WAS PROVED AGAINST. Deleting the fallback clause from the GPU worker's
prompt, which leaves the worker with evidence rules and no answer for the case
where there is no evidence.

GUARDS. The twin rule in `apps/notulen/CLAUDE.md`.
"""
from __future__ import annotations

import inspect
import pytest


# From a notulen names each person once and caps the speakers.

import importlib.util


import os


from pathlib import Path


from types import ModuleType


# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")


from apps.notulen.app.core.sessions.attendee_list import (  # noqa: E402
    clean_attendees,
)


WORKER = Path(__file__).resolve().parents[1] / "entrypoints/worker.py"


#: One person spelled two ways, on a meeting with two people on it.
AS_IT_ARRIVED = ["alice", "bob", "Bob"]


#: Two speakers of ten seconds each, and two strays of one second. Every stray
#: touches one kept voice and sits nine seconds from the other.
TURNS = [
    (0.0, 10.0, "A"),
    (10.0, 11.0, "stray-1"),
    (20.0, 30.0, "B"),
    (30.0, 31.0, "stray-2"),
    (40.0, 50.0, "A"),
]


def _worker(attendees: str) -> ModuleType:
    """Import the GPU worker with a job's env in place.

    It reads its config at module scope on purpose (fail-fast before GPU time
    is spent), so there is no other way in. Loaded by path and never into
    `sys.modules`, so each case gets its own module.
    """
    before = dict(os.environ)
    os.environ.update({
        "JOB_ID": "00000000-0000-0000-0000-000000000000",
        "AUDIO_KEY": "notulen/audio/test.webm",
        "TITLE": "Alice & Bob",
        "MEETING_DATE": "2026-01-15",
        "ATTENDEES": attendees,
        "DB_URL": "postgresql://nobody@127.0.0.1/nowhere",
    })
    try:
        spec = importlib.util.spec_from_file_location("notulen_worker_under_test", WORKER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(before)


def _one_person_spelled_two_ways_is_one_attendee() -> None:
    """The dashboard's own cleaner keeps the order and the capitalised spelling."""
    assert clean_attendees(AS_IT_ARRIVED) == ["alice", "Bob"]


def _the_worker_reads_the_same_list_the_same_way() -> None:
    """The twin: the worker's own parse must agree, name for name."""
    worker = _worker(",".join(AS_IT_ARRIVED))
    assert worker.ATTENDEES == clean_attendees(AS_IT_ARRIVED)


def _two_people_leave_two_voices_in_the_transcript() -> None:
    """Each stray goes to the voice it touches, and nobody else survives."""
    worker = _worker(",".join(AS_IT_ARRIVED))
    assert worker._voices_to_keep(worker.ATTENDEES) == 2
    assert worker._fold_stray_voices(TURNS, 2) == [
        (0.0, 10.0, "A"),
        (10.0, 11.0, "A"),
        (20.0, 30.0, "B"),
        (30.0, 31.0, "B"),
        (40.0, 50.0, "A"),
    ]


def _a_list_too_thin_to_trust_folds_nothing() -> None:
    """An unnamed guest is dropped from the participant list, so one name can
    mean two people in the room. Leaving the voices alone beats merging them."""
    worker = _worker("Alice")
    assert worker._voices_to_keep(worker.ATTENDEES) is None
    assert worker._voices_to_keep([]) is None
    assert worker._fold_stray_voices(TURNS, None) == TURNS


def _fewer_voices_than_people_are_left_alone() -> None:
    """Three people and two voices means somebody said nothing, not a stray."""
    worker = _worker("Alice,Bob,Carol")
    quiet_call = TURNS[:1] + TURNS[2:3]
    assert worker._fold_stray_voices(quiet_call, 3) == quiet_call

# From a notulen never names a speaker the transcript does not place.

import sys


from types import ModuleType as ModuleType_2, SimpleNamespace


# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")


from apps.notulen.app.core.minutes import notulen_writer  # noqa: E402


#: An unconditional mapping order: it orders a mapping and gives the writer no
#: way to decline one.
THE_UNCONDITIONAL_MAPPING_ORDER = (
    "Link the speaker labels to the attendees based on context."
)


#: What minutes have to carry when the audio places nobody.
A_LABEL_TO_FALL_BACK_ON = "Speaker 1"


#: Who was in the room.
ATTENDEES = ["Alice", "Bob"]


#: Labelled blocks, and no attendee named in any of them. Never read by
#: Claude here, only carried through the seam.
TRANSCRIPT = (
    "[00:00] [SPEAKER_00] Shall we start with the planning.\n\n"
    "[00:12] [SPEAKER_01] Fine, I have the numbers with me.\n"
)


def _speaker_rule(system_prompt: str) -> str:
    """The paragraph that decides who a voice is: what sits between the
    attendee line and the template, minus the attendee names themselves."""
    below_attendees = system_prompt.split("ATTENDEES:", 1)[1]
    paragraph = below_attendees.split("\nTEMPLATE:", 1)[0]
    return paragraph.split("\n", 1)[1].strip()


def _fake_anthropic(captured: list[str]) -> ModuleType_2:
    """Just enough SDK for `_generate_notulen` to finish: a client, one message,
    and a usage count to price."""
    module = ModuleType_2("anthropic")

    class Messages:
        def create(self, **call: object) -> SimpleNamespace:
            captured.append(str(call["system"]))
            return SimpleNamespace(
                content=[SimpleNamespace(text="# Meeting")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    class Anthropic:
        def __init__(self) -> None:
            self.messages = Messages()

    module.Anthropic = Anthropic  # type: ignore[attr-defined]
    return module


def _worker_2() -> ModuleType_2:
    """Import the GPU worker with a job's env in place.

    It reads its config at module scope on purpose (fail-fast before GPU time
    is spent), so there is no other way in. Loaded by path and never into
    `sys.modules`.
    """
    before = dict(os.environ)
    os.environ.update({
        "JOB_ID": "00000000-0000-0000-0000-000000000000",
        "AUDIO_KEY": "notulen/audio/test.webm",
        "TITLE": "Alice & Bob",
        "MEETING_DATE": "2026-01-15",
        "ATTENDEES": ",".join(ATTENDEES),
        "DB_URL": "postgresql://nobody@127.0.0.1/nowhere",
    })
    try:
        spec = importlib.util.spec_from_file_location("notulen_worker_under_test", WORKER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(before)


def _worker_prompt() -> str:
    """What the GPU worker hands Claude. The SDK and the cost bookkeeping are
    stood in for; neither is what this pins."""
    worker = _worker_2()
    captured: list[str] = []
    worker._log_ai_call = lambda *unused, **also_unused: None
    before = sys.modules.get("anthropic")
    sys.modules["anthropic"] = _fake_anthropic(captured)
    try:
        worker._generate_notulen(TRANSCRIPT)
    finally:
        if before is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = before
    return captured[0]


def _writer_prompt() -> str:
    """What the CPU twin hands Claude, with the API call stood in for."""
    captured: list[str] = []

    def capture(**call: object) -> dict[str, str]:
        captured.append(str(call["system_prompt"]))
        return {"content": "# Meeting"}

    before = notulen_writer.call_claude
    notulen_writer.call_claude = capture
    try:
        notulen_writer.generate_notulen(
            transcript=TRANSCRIPT,
            title="Alice & Bob",
            meeting_date="2026-01-15",
            attendees=ATTENDEES,
            job_id="00000000-0000-0000-0000-000000000000",
        )
    finally:
        notulen_writer.call_claude = before
    return captured[0]


def _neither_twin_orders_an_unconditional_mapping() -> None:
    """The sentence that swaps a meeting is in neither prompt."""
    assert THE_UNCONDITIONAL_MAPPING_ORDER not in _worker_prompt()
    assert THE_UNCONDITIONAL_MAPPING_ORDER not in _writer_prompt()


def _both_twins_leave_a_label_to_fall_back_on() -> None:
    """With no evidence there has to be something to write that is not a name."""
    assert A_LABEL_TO_FALL_BACK_ON in _speaker_rule(_worker_prompt())
    assert A_LABEL_TO_FALL_BACK_ON in _speaker_rule(_writer_prompt())


def _the_two_twins_carry_the_same_speaker_rule() -> None:
    """The twin rule, on the one paragraph that decides who a voice is."""
    assert _speaker_rule(_worker_prompt()) == _speaker_rule(_writer_prompt())


def _the_rule_itself_names_nobody_who_was_in_the_room() -> None:
    """The attendee list is above the rule and the rule stays generic. A rule
    that repeats the names is a rule handing the writer names to reach for,
    and a writer reaching for names can map voices to the wrong people."""
    rule = _speaker_rule(_worker_prompt())
    assert not [name for name in ATTENDEES if name in rule]


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
    *_cases(_one_person_spelled_two_ways_is_one_attendee),
    *_cases(_the_worker_reads_the_same_list_the_same_way),
    *_cases(_two_people_leave_two_voices_in_the_transcript),
    *_cases(_a_list_too_thin_to_trust_folds_nothing),
    *_cases(_fewer_voices_than_people_are_left_alone),
    *_cases(_neither_twin_orders_an_unconditional_mapping),
    *_cases(_both_twins_leave_a_label_to_fall_back_on),
    *_cases(_the_two_twins_carry_the_same_speaker_rule),
    *_cases(_the_rule_itself_names_nobody_who_was_in_the_room),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_notulen_names_each_person_once_caps_the_speakers_and_never_names_one_the_transcript_does_not_place(scenario, given, uses, request):
    """A notulen names each person once, caps the speakers, and never names a speaker the transcript does not place: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
