"""Handing corrected minutes to the assistant (``core/board/``).

The dashboard decides nothing about what goes on the board: it takes the
one-shot claim, posts the meeting to the assistant, and records what came
back. The assistant is where the judgement lives.

Module map (one public callable per file):
    claim_send.py         claim_send(job_id) -> bool: the test-and-set that makes
                          the send button fire once, however often it is pressed
    send_to_assistant.py  send_to_assistant(...) -> list[int]: post the meeting to
                          the assistant's bearer-gated route, return the issues
"""
from __future__ import annotations

from apps.notulen.app.core.board.claim_send import claim_send
from apps.notulen.app.core.board.send_to_assistant import (
    AssistantUnreachable,
    send_to_assistant,
)

__all__ = ["AssistantUnreachable", "claim_send", "send_to_assistant"]
