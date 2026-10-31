"""Output truncation shared by every tool module.

One home for the per-result byte budget (campaign rule: one home per
duplicated constant, `gh_issue_view` used to hardcode the same 8192
literal that `k8s` declared). Long tool results would bloat the LLM
context and the daily budget cap.

FAILURE POLICY: pure string transform, nothing to fail.
"""
from __future__ import annotations

# Truncation budget, 8 KiB per tool result is plenty for a traceback
# or an issue thread excerpt.
_MAX_BYTES_PER_RESULT = 8192


def truncate(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= _MAX_BYTES_PER_RESULT:
        return text
    head = encoded[:_MAX_BYTES_PER_RESULT].decode("utf-8", errors="ignore")
    return head + f"\n... [truncated; original {len(encoded)} bytes]"


def _first_bytes(text: str, budget: int) -> str:
    """At most the first `budget` UTF-8 bytes of `text`, never splitting a character."""
    return text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")


def _last_bytes(text: str, budget: int) -> str:
    """At most the last `budget` UTF-8 bytes of `text`, never splitting a character."""
    if budget <= 0:
        return ""
    return text.encode("utf-8")[-budget:].decode("utf-8", errors="ignore")


def truncate_keep_tail(head: str, tail: str) -> str:
    """Fit `head + tail` in the budget by cutting the START of `tail`.

    For a thread read oldest first, such as an issue overview followed by its
    comments. `truncate` keeps the first bytes, so it would cut the NEWEST comments and
    leave the answer resting on a stale status. The head keeps at most half the
    budget, so a long body cannot crowd the newest comment out, and both cuts
    are marked.
    """
    if len((head + tail).encode("utf-8")) <= _MAX_BYTES_PER_RESULT:
        return head + tail
    head_bytes = len(head.encode("utf-8"))
    kept_head = head
    if head_bytes > _MAX_BYTES_PER_RESULT // 2:
        kept_head = (
            _first_bytes(head, _MAX_BYTES_PER_RESULT // 2)
            + f"\n... [body cut; original {head_bytes} bytes]\n"
        )
    tail_bytes = len(tail.encode("utf-8"))
    # Room for the marker line itself, so the whole result stays in budget.
    room = _MAX_BYTES_PER_RESULT - len(kept_head.encode("utf-8")) - 96
    kept_tail = _last_bytes(tail, room)
    dropped = tail_bytes - len(kept_tail.encode("utf-8"))
    return (
        f"{kept_head}... [oldest {dropped} of {tail_bytes} bytes cut; "
        f"the newest part is kept]\n{kept_tail}"
    )
