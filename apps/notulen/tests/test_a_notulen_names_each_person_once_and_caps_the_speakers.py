"""A set of minutes names each person once, and carries no more voices than there were people.

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
"""
from __future__ import annotations

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


def test_one_person_spelled_two_ways_is_one_attendee() -> None:
    """The dashboard's own cleaner keeps the order and the capitalised spelling."""
    assert clean_attendees(AS_IT_ARRIVED) == ["alice", "Bob"]


def test_the_worker_reads_the_same_list_the_same_way() -> None:
    """The twin: the worker's own parse must agree, name for name."""
    worker = _worker(",".join(AS_IT_ARRIVED))
    assert worker.ATTENDEES == clean_attendees(AS_IT_ARRIVED)


def test_two_people_leave_two_voices_in_the_transcript() -> None:
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


def test_a_list_too_thin_to_trust_folds_nothing() -> None:
    """An unnamed guest is dropped from the participant list, so one name can
    mean two people in the room. Leaving the voices alone beats merging them."""
    worker = _worker("Alice")
    assert worker._voices_to_keep(worker.ATTENDEES) is None
    assert worker._voices_to_keep([]) is None
    assert worker._fold_stray_voices(TURNS, None) == TURNS


def test_fewer_voices_than_people_are_left_alone() -> None:
    """Three people and two voices means somebody said nothing, not a stray."""
    worker = _worker("Alice,Bob,Carol")
    quiet_call = TURNS[:1] + TURNS[2:3]
    assert worker._fold_stray_voices(quiet_call, 3) == quiet_call
