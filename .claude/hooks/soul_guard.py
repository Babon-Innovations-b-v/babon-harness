#!/usr/bin/env python3
"""Stop hook: the two soul rules that a machine can check, checked.

`.claude/soul.md` is replayed into every prompt by the UserPromptSubmit hook,
and replaying a rule is asking for it. Prose in a prompt is a request rather
than a rule: sessions break rules 2, 3 and 5 in their own replies while
explaining why prose does not work. So this is the seam.

Two rules and no more, because only two are mechanically decidable:

- Rule 3, no em dashes. Exact, no judgement, no false positive.
- Rules 2 and 5, length tracks the answer and not the prompt. Not decidable as
  written ("the shortest version that is still fully clear" is a judgement), so
  what is checked is the proxy the failure actually takes: a long reply to a
  short question that did not ask for detail.

Rules 1, 4, 6 and 7 (plain language, no preamble, warmth, English) stay
requests. A word list cannot tell jargon from the right technical term, and a
guard that looks like protection and is not is worse than none.

It blocks at most ONCE per stop, and a re-sent reply goes through. That is
deliberate and its shape is nudge, then allow. A long
answer is sometimes the right answer, and a guard that can veto one would be a
guard that suppresses a report. What it buys is that the length is chosen
rather than drifted into.

FAILURE POLICY: fail-open. Anything unreadable, any unexpected shape, any
exception exits 0 with no output, which ends the turn normally. A session that
cannot answer is worse than a session that answers too long.
`SOUL_GUARD=0` disarms it.
"""

import json
import os
import re
import sys

EM_DASH = "\u2014"

#: Over this many words, a reply is long enough to be worth one second look.
#: 120 is several times the typical length of a short answer, so it stops only
#: the tail a reader would call too long: the tail is the failure, not the norm.
LONG_REPLY_WORDS = 120

#: At or under this, the question is short, so a long answer is answering
#: something the reader did not ask.
SHORT_QUESTION_WORDS = 25

#: Not a question at all: a task notification, a hook line or a system
#: reminder arrives in the user role, and a report answering one is not a long
#: answer to a short question. Excluded so the guard fires on the failure it
#: was built for rather than on every finished background job.
NOT_A_QUESTION = re.compile(r"^\s*<(task-notification|system-reminder|local-command)")

#: Asked for depth, so length is what was wanted. Kept to phrases that request
#: elaboration rather than to any long word list: this is the one place a
#: judgement is made, and it should stay small enough to read.
ASKED_FOR_DETAIL = re.compile(
    r"\b(explain|walk me through|in detail|deep dive|full (report|picture|"
    r"breakdown)|everything|elaborate|why does|how does|write up|document|"
    r"summar(y|ise|ize) of)\b",
    re.IGNORECASE,
)


def last_turns(transcript_path):
    """The final assistant text and the user text before it, or (None, None).

    Reads the transcript JSONL rather than being handed the message, because
    the Stop payload does not carry it. A line that will not parse is skipped:
    a malformed row must not cost the check, and must not end the turn either.
    """
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            rows = [line for line in handle if line.strip()]
    except OSError:
        return None, None
    assistant, user = None, None
    for line in reversed(rows):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") or {}
        role = message.get("role")
        if role not in ("assistant", "user"):
            continue
        text = text_of(message)
        if not text:
            continue
        if role == "assistant" and assistant is None:
            assistant = text
        elif role == "user" and assistant is not None:
            user = text
            break
    return assistant, user


def text_of(message):
    """The prose of one transcript message, tool calls and results dropped."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def broken_rules(assistant, user):
    """Which checkable rules this reply breaks, as reasons to hand back."""
    found = []
    if EM_DASH in assistant:
        count = assistant.count(EM_DASH)
        found.append(
            f"Rule 3: your reply carries {count} em dash"
            f"{'es' if count > 1 else ''}. Use a comma, a colon or a semicolon."
        )
    words = len(assistant.split())
    if words > LONG_REPLY_WORDS and user is not None:
        asked_short = len(user.split()) <= SHORT_QUESTION_WORDS
        wanted_detail = bool(ASKED_FOR_DETAIL.search(user))
        machine_turn = bool(NOT_A_QUESTION.match(user))
        if asked_short and not wanted_detail and not machine_turn:
            found.append(
                f"Rules 2 and 5: {words} words answering a "
                f"{len(user.split())}-word question that did not ask for "
                "detail. Lead with the plain answer and stop; having just "
                "processed a lot does not license a long reply."
            )
    return found


def main():
    if os.environ.get("SOUL_GUARD", "1") == "0":
        return
    payload = json.loads(sys.stdin.read())
    # One block per stop. Without this the rewrite is checked again and a
    # reply that cannot satisfy the guard would never reach the reader.
    if payload.get("stop_hook_active"):
        return
    transcript = payload.get("transcript_path")
    if not transcript:
        return
    assistant, user = last_turns(transcript)
    if not assistant:
        return
    found = broken_rules(assistant, user)
    if not found:
        return
    print(json.dumps({
        "decision": "block",
        "reason": (
            "Your reply breaks a soul rule that is checked rather than asked "
            "for (.claude/soul.md):\n"
            + "\n".join(f"  {item}" for item in found)
            + "\nRewrite it and answer again. This is said once per turn, so a "
            "reply you send again goes through: if the length is deliberate, "
            "keep it."
        ),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: a turn that cannot end is worse than a turn that runs long.
        pass
    sys.exit(0)
