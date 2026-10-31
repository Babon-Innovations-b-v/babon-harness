"""One sent message against the readings recorded beside it.

The rules are `core.claims`' rules, called and never copied. A guard runs on a
DRAFT and may nudge; this runs on what was SENT and may only report. That is
the whole of the difference, and it is why nothing here compiles a pattern of
its own: a checker with rules of its own would report messages the guards were
always going to allow, which is a fact about the checker rather than about
The assistant. A test reads this package for `re.compile` and fails on one.

WHICH RULES ARE IN, AND WHY EACH IS.

  the five `claims.SENTENCE_RULES`   the claim defects a sent message can carry
  `unread_stamp`                     a clock time no reading contains ("stuck
                                     since ~09:35 UTC" when the timers said
                                     otherwise); no existing guard covers it
  `command_syntax`                   a hand-off ("run journalctl -u ..."). A
                                     page naming "Unit example.service" does
                                     not read as an invocation:
                                     `signal_text.names_a_command` needs an
                                     operand, and a unit name alone is not one.
  `unbacked_causal_claim`            takes the read count AND the read text,
  `unbacked_board_statement`         both of which a recorded row now carries
  `fabricated_issue_numbers`

WHICH ARE OUT. `wrong_language` needs the reader's language, and it would fire on
most messages that were correct in their reader's own language. `unsupported_liveness` needs the evidence bundle as typed
`Fact`s with their subjects; a recorded reading carries the value and not the
subject map, so calling it would judge against something it was not given.
Both are guards that already run on the draft, so leaving them out here costs a
second look and not a first one.

WHAT IT CANNOT SEE AT ALL. A message from a teammate that never reached the
assistant is not a claim in a message, and no checker over sent text can
surface a message that was never sent: that is a delivery failure,
answered by counting unanswered inbound, not by reading outbound.

A FIRST RUN OVER HISTORY EXERCISES ONLY THE TEXT-ONLY RULES. The readings for
every message sent before the recording shipped do not exist, so with no
evidence in hand `unread_stamp` returns False by construction and the three
whole-message guards see a read count of zero. That is not a gap to paper over;
it is the honest shape of a backfill.

FAILURE POLICY: pure functions, no I/O, no sending, no nudging, no blocking.
The package reports and does nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from apps.assistant.core import claims

# An outcome that counts as having actually looked. `core.chat` and
# `core.patrol` write this word onto a reading when the result was neither
# UNAVAILABLE nor FAILED, which is the same test their read counters use.
READ_OK = "ok"


@dataclass(frozen=True)
class Finding:
    """One thing a sent message said that its readings do not support."""

    rule: str
    sentence: str
    says: str


def check(
    message_text: str, readings: Sequence[Mapping[str, Any]]
) -> tuple[Finding, ...]:
    """Every finding in one sent message, in the order the message reads."""
    text = (message_text or "").strip()
    if not text:
        return ()
    evidence = evidence_text(readings)
    found = list(_per_sentence(text, evidence))
    found.extend(_whole_message(text, readings, evidence))
    return tuple(found)


def evidence_text(readings: Sequence[Mapping[str, Any]]) -> str:
    """Everything the loop read, as one block to match words against.

    Only the readings that actually returned data. An UNAVAILABLE render is not
    evidence, and folding it in would let a tool that answered nothing back a
    number in the message.
    """
    return "\n".join(
        str(reading.get("excerpt", ""))
        for reading in readings
        if str(reading.get("outcome", "")) == READ_OK
    )


def _per_sentence(text: str, evidence: str):
    """The rules that judge one sentence at a time."""
    for sentence in claims._SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for rule in claims.SENTENCE_RULES:
            if rule.holds(sentence):
                yield Finding(rule.name, sentence, rule.says)
        if claims.unread_stamp(sentence, evidence):
            yield Finding(
                "unread_stamp",
                sentence,
                "carries a date, time or number that no recorded reading contains",
            )


def _whole_message(
    text: str, readings: Sequence[Mapping[str, Any]], evidence: str
):
    """The rules that need the whole message and the readings behind it."""
    successful = sum(
        1 for reading in readings if str(reading.get("outcome", "")) == READ_OK
    )
    board = sum(
        1
        for reading in readings
        if str(reading.get("outcome", "")) == READ_OK
        and str(reading.get("tool", "")).startswith("gh_")
    )
    for rule, nudge in (
        ("unbacked_causal_claim", claims.unbacked_causal_claim(text, successful, evidence)),
        (
            "announced_check_never_made",
            claims.announced_check_never_made(text, successful),
        ),
        ("unbacked_board_statement", claims.unbacked_board_statement(text, board)),
        (
            "fabricated_issue_numbers",
            claims.fabricated_issue_numbers(text, claims.issue_numbers_in(evidence)),
        ),
        ("command_syntax", claims.command_syntax(text)),
    ):
        if nudge:
            yield Finding(rule, text, _said_for(rule))


def _said_for(rule: str) -> str:
    """The one line a finding prints, for the whole-message rules.

    Their guards return a nudge written at a model mid-draft ("Do NOT mention
    this note"), which reads as nonsense in a report a person opens on a Monday
    morning, so the report says it in its own words.
    """
    return {
        "unbacked_causal_claim": (
            "names a cause the readings behind it do not support"
        ),
        "unbacked_board_statement": (
            "states something about the board with no GitHub read behind it"
        ),
        "fabricated_issue_numbers": (
            "cites an issue number no tool returned"
        ),
        "command_syntax": (
            "hands the reader a command to run instead of the answer"
        ),
        "announced_check_never_made": (
            "says it would need to check something, in a turn that read nothing"
        ),
    }[rule]
