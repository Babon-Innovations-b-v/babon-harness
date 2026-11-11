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

It blocks at most twice per turn (MAX_BLOCKS), so a turn can always end. Its message asks
for the short rewrite outright: an earlier wording let a session "keep it if
deliberate", and sessions re-sent the same long reply.

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
#: Measured, not guessed: across 63 replies to a short question in one session,
#: the median was 23 words and the tail ran 356, 187, 162, 157, 143, 137, 129.
#: 120 is over five times the median and stops 8 of the 63, which are the eight
#: a reader would call too long, so the tail is the failure and not the norm.
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
    r"summar(y|ise|ize) of|list (me )?(all|every)|all the|full list|every one)\b",
    re.IGNORECASE,
)


#: How many times one turn may be sent back before its reply goes through.
MAX_BLOCKS = 2


def _counter_path(payload):
    """The temp file that counts this session's blocks in the current turn."""
    import tempfile
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", "none")))
    return os.path.join(tempfile.gettempdir(), f"soul-guard-{session}.count")


def _blocks_so_far(payload):
    """How many times this turn has already been sent back."""
    try:
        with open(_counter_path(payload), encoding="utf-8") as handle:
            return int(handle.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _count_block(payload):
    """Record one more block for this turn; a new turn starts from zero."""
    count = _blocks_so_far(payload) + 1 if payload.get("stop_hook_active") else 1
    with open(_counter_path(payload), "w", encoding="utf-8") as handle:
        handle.write(str(count))


def _reset_blocks(payload):
    """A reply that passes ends the turn's count."""
    try:
        os.remove(_counter_path(payload))
    except OSError:
        pass


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
    # At most MAX_BLOCKS blocks per turn, counted per session in a temp file,
    # so a rewrite that is still too long is sent back once more, and a turn
    # can always end.
    if payload.get("stop_hook_active") and _blocks_so_far(payload) >= MAX_BLOCKS:
        return
    transcript = payload.get("transcript_path")
    if not transcript:
        return
    assistant, user = last_turns(transcript)
    if not assistant:
        return
    found = broken_rules(assistant, user)
    if not found:
        _reset_blocks(payload)
        return
    _count_block(payload)
    print(json.dumps({
        "decision": "block",
        "reason": (
            "Your reply breaks a soul rule that is checked rather than asked "
            "for (.claude/soul.md):\n"
            + "\n".join(f"  {item}" for item in found)
            + "\nRewrite it now: the plain answer in a few lines, under "
            f"{LONG_REPLY_WORDS} words, and at most one line offering detail. "
            "Sending the same reply again is not an answer to this."
        ),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: a turn that cannot end is worse than a turn that runs long.
        pass
    sys.exit(0)
