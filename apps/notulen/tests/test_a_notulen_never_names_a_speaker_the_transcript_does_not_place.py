"""A set of minutes never names a speaker the transcript does not place.

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

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")

from apps.notulen.app.core.minutes import notulen_writer  # noqa: E402

WORKER = Path(__file__).resolve().parents[1] / "entrypoints/worker.py"

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


def _fake_anthropic(captured: list[str]) -> ModuleType:
    """Just enough SDK for `_generate_notulen` to finish: a client, one message,
    and a usage count to price."""
    module = ModuleType("anthropic")

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


def _worker() -> ModuleType:
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
    worker = _worker()
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


def test_neither_twin_orders_an_unconditional_mapping() -> None:
    """The sentence that swaps a meeting is in neither prompt."""
    assert THE_UNCONDITIONAL_MAPPING_ORDER not in _worker_prompt()
    assert THE_UNCONDITIONAL_MAPPING_ORDER not in _writer_prompt()


def test_both_twins_leave_a_label_to_fall_back_on() -> None:
    """With no evidence there has to be something to write that is not a name."""
    assert A_LABEL_TO_FALL_BACK_ON in _speaker_rule(_worker_prompt())
    assert A_LABEL_TO_FALL_BACK_ON in _speaker_rule(_writer_prompt())


def test_the_two_twins_carry_the_same_speaker_rule() -> None:
    """The twin rule, on the one paragraph that decides who a voice is."""
    assert _speaker_rule(_worker_prompt()) == _speaker_rule(_writer_prompt())


def test_the_rule_itself_names_nobody_who_was_in_the_room() -> None:
    """The attendee list is above the rule and the rule stays generic. A rule
    that repeats the names is a rule handing the writer names to reach for,
    and a writer reaching for names can map voices to the wrong people."""
    rule = _speaker_rule(_worker_prompt())
    assert not [name for name in ATTENDEES if name in rule]
