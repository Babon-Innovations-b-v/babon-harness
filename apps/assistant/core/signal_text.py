"""Shared Signal-message cleanup for openclaw's LLM loops.

Every loop that produces a Signal message (the monitor digest,
the notify processor) tells the model to wrap its finished message in
<note>...</note> and to write plain text. Models reliably reason out loud
first and leak markdown despite the prompt, so these two helpers clean the
output deterministically:

- `extract_note(text)` pulls the message out of its tags, dropping the
  scratchpad preamble; it falls back to the whole text if the tags are
  missing, so a real message is never lost to a formatting slip.
- `split_for_signal(text)` packs a finished message into Signal-sized pieces
  at whitespace, the one overflow policy every human-facing prose loop uses.
- `strip_markdown(note)` defangs the markdown Signal would render literally
  AND strips any hallucinated tool-call / function-call markup: the model
  sometimes imitates an operator and writes out `<function_calls>` /
  `<invoke ...>` XML or "$ ssh ..." command lines as if executing them
  (a runbook-heavy alert body can trigger it). That is
  broken output, not language; it is defanged here as a hard backstop even
  though the prompt (`core.voice`) also forbids it. It repairs the two voice
  rules that are mechanical too: a command written for the reader to run goes
  (`core.voice` again), and an em dash becomes the comma the house style uses
  (soul.md rule 5).

One home for all so the loops do not each carry a copy.
"""
from __future__ import annotations

import re

from apps.assistant.core.limits import SIGNAL_MAX_CHARS

_NOTE_RE = re.compile(r"<note>(.*?)</note>", re.DOTALL | re.IGNORECASE)
# Any angle-bracket tag (real tool-call markup is <function_calls>,
# <invoke ...>, <parameter ...>, closing </...>). Signal never renders
# these as anything but literal noise, so drop every <...> tag.
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
# A line that is the model pretending to run a command. Broad, because a line
# that OPENS with a tool name is a command line whatever follows it.
_CMD_LINE_RE = re.compile(
    r"^\s*(\$\s|#\s*ssh\b|ssh\s+\w|sudo\s|kubectl\s|docker\s|git\s|python[3]?\s+-m"
    # The read-only ones, at the start of a line only: mid-sentence each of
    # these is usually a plain word, which is why `_BINARIES` leaves them out.
    # Held pages have carried them whole.
    r"|(?:ls|grep|tail|cat|curl)\s+\S)",
)
# What is left of a fix step once its command is gone. Dropping only the
# command line would leave the sentences around it, so a page could end on a
# lead-in with nothing after it, or open a paragraph on a "Then ..." with no
# first step before it. The line that introduced the command ends in a colon;
# the line that continues it opens with one of these words.
_LEAD_IN_RE = re.compile(r":\s*$")
_FOLLOW_ON_RE = re.compile(r"^\s*(?:Then|Also|After that)\b")
# The same hand-off written INTO a sentence: "Worth checking on the VM: sudo
# systemctl status harness-textfile.timer". `core.voice` forbids
# writing command syntax at all (run the safe read-only ones yourself, then say
# what you found), and the line anchor above catches only the command that
# starts a line, while most hand-offs sit mid-sentence.
# `_names_an_invocation` below is the mid-sentence half, and it is deliberately
# harder to trip than the line-anchored one, because at the start of a line a
# tool name IS a command while mid-sentence it is usually a noun.
#: The tool names that can start an invocation. A name alone proves nothing:
#: mid-sentence every one of these is also an ordinary noun ("the docker
#: container", "the sudo password", "git history").
_BINARIES = frozenset({
    "sudo", "systemctl", "journalctl", "kubectl", "docker", "git", "ssh",
    "scp", "dmesg", "psql", "helm", "promtool", "amtool",
})
#: What separates an invocation from a sentence that names a tool: an OPERAND.
#: A flag, a path, an assignment, or a name carrying a dot or two hyphenated
#: parts. Ordinary English words after a tool name ("compose stack came back",
#: "status is clean", "status on the timer") are none of those.
_OPERAND_RE = re.compile(
    r"^(?:-{1,2}[\w-]+"           # -a, --tail, --replicas=1
    r"|[\w@/.:=-]*[./=@][\w@/.:=-]*"  # a.service, /var/log/x, app=harness-api
    r"|\w+(?:-\w+)+)$"            # kube-state-metrics, dead-mans-switch
)
#: How far past the tool name an operand still counts as part of the same
#: invocation: "sudo systemctl status harness-webhook.service" needs
#: three, and beyond four the words belong to the sentence, not the command.
_OPERAND_WINDOW = 4
# Sentence boundary, same shape as `claims._SENTENCE_SPLIT_RE`. Kept local so
# this leaf module keeps importing nothing but `limits`.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# A JSON function-call the model typed out as text instead of making a real
# tool call: {"name": "bash", "arguments": {"command": "..."}} (OpenAI-style,
# NOT Anthropic's block form). A model can emit a whole fabricated
# docker/deploy transcript this way. `strip_markdown` drops
# such lines; `looks_fabricated` treats their presence as a broken message.
_JSON_CALL_RE = re.compile(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:', re.IGNORECASE)
_JSON_CMD_RE = re.compile(r'"arguments"\s*:\s*\{[^}]*"command"\s*:', re.IGNORECASE)
# Fabricated command OUTPUT the model invents to go with the fake calls:
# syslog-style deploy lines and docker-ps headers it could not have run.
_FAKE_OUTPUT_RE = re.compile(
    r"(deploy\.sh\[\d+\]|CONTAINER ID\s+(NAMES|IMAGE)|^\s*[0-9a-f]{12}\s+harness-)",
    re.MULTILINE,
)
# soul.md rule 5: no em dashes, use commas, colons, semicolons. The rule is
# mechanical, and where the voice prompt itself is written with them the
# assistant writes the punctuation it is shown. An em dash is not a crisis, so this
# REPAIRS rather than refuses: the pause becomes the comma the house style
# uses. Between two numbers the dash is a range and not a pause, so that one
# becomes a plain hyphen instead (a clock range stays a clock range); a
# trailing one has nothing left to separate and just goes.
#
# The range rule is TIGHT, and it has to be. A range is written closed up
# ("10:00\u201411:00"), while a dash with spaces around it is a pause in a sentence
# that happens to sit next to a number. A message like "Four
# Mondays booked \u2014 Mar 2, 9, 16, 23 \u2014 10:00 to 11:00" shows why: a loose
# version of this rule would turn the second pause into "23-10:00", which reads
# as a date range and is not one. Requiring no spaces costs nothing: a real range is
# never written with them.
_EM_DASH_RANGE_RE = re.compile(r"(?<=\d)\u2014(?=\d)")
_EM_DASH_TRAILING_RE = re.compile(r"\s*\u2014\s*$")
_EM_DASH_RE = re.compile(r"\s*\u2014\s*")


def looks_fabricated(text: str) -> bool:
    """True when the message is a made-up terminal session rather than an
    answer: the model typed JSON tool-calls as prose, or invented command
    output. The assistant has no shell/docker on the VM, so this is broken output, not
    language. Loops suppress a message that trips this (patrol -> QUIET, chat
    -> honest fallback) instead of sending the fabrication."""
    if _JSON_CALL_RE.search(text) or _JSON_CMD_RE.search(text):
        return True
    return len(_FAKE_OUTPUT_RE.findall(text)) >= 2


def text_of(response: object) -> str:
    """Join an Anthropic message's text blocks into one stripped string.

    Every LLM loop needs the model's prose out of a tool-use response the
    same way; this is that one extraction (was a byte-identical `_extract_text`
    in chat, patrol, advise, digest and security_judge). Duck-typed on
    `response.content` blocks so this module keeps no anthropic import."""
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", "")
    ]
    return "".join(parts).strip()


def is_sentinel(message: str, token: str) -> bool:
    """True when the model's final non-empty line is exactly `token`, the
    loops' silence protocol (QUIET for patrol/advise/security_judge, SILENT
    for the monitor digest / notify flush). Models reason out loud first and
    put the bare token on the last line, so only the final line is checked."""
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return bool(lines) and lines[-1] == token


def split_for_signal(text: str) -> list[str]:
    """Pack a finished message into SIGNAL_MAX_CHARS-sized pieces, breaking
    ONLY at whitespace so a piece never ends mid-word.

    The overflow policy for human-facing prose, in one home, so that no loop
    (a weekly advisor, say) sends a note of thousands of characters as one
    message: the cap is declared in `core/limits` for every Signal message, and the two
    autonomous beats were the paths that never applied it. Prose is split, not
    truncated like the triage draft, because a cut drops the ask at the end of
    the note.

    Returns one piece for a message that already fits (the normal case), and
    a single empty piece for empty text, so callers can always send the first
    piece and treat the rest as follow-ups.
    """
    text = text.strip()
    pieces: list[str] = []
    remaining = text
    while len(remaining) > SIGNAL_MAX_CHARS:
        window = remaining[:SIGNAL_MAX_CHARS]
        # Prefer a paragraph/line break, else the last space; only hard-cut if
        # the window is one unbroken token (e.g. a giant URL).
        cut = max(window.rfind("\n"), window.rfind(" "))
        if cut <= 0:
            cut = SIGNAL_MAX_CHARS
        pieces.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    pieces.append(remaining)
    return pieces


def extract_note(text: str) -> str:
    """Return the text inside <note>...</note>, or the whole stripped text if
    the tags are absent."""
    match = _NOTE_RE.search(text)
    return (match.group(1) if match else text).strip()


def _names_an_invocation(sentence: str) -> bool:
    """True when `sentence` contains a tool name followed by a real operand.

    The mid-sentence half of the command guard. Matching a tool name plus one
    of its own subcommands reads as a sound rule and is not: it would delete
    "the docker compose stack came back on its own" or "git status is clean,
    nothing uncommitted", which are the news rather than a hand-off. That seam
    is `compose` against `container`, not command against prose.

    An operand is what actually separates the two, because English does not
    produce one by accident. Erring toward keeping the sentence is deliberate:
    a tool name left in a sentence is untidy, a deleted sentence is the message
    The owner needed.
    """
    tokens = sentence.split()
    for index, token in enumerate(tokens):
        if token.strip("`'\",.;:()").lower() not in _BINARIES:
            continue
        window = tokens[index + 1: index + 1 + _OPERAND_WINDOW]
        if any(_OPERAND_RE.match(word.strip("`'\",.;:()")) for word in window):
            return True
    return False


def names_a_command(text: str) -> bool:
    """True when the message hands the reader a shell command to run, either
    as its own line or inside a sentence.

    The detection half of the strip below, exposed so a loop that CAN ask the
    model again (`claims.command_syntax` on chat and patrol) nudges before the
    strip has to cut anything."""
    return any(
        _CMD_LINE_RE.match(line) or _names_an_invocation(line)
        for line in text.splitlines()
    )


def _drop_command_sentences(line: str) -> str:
    """Drop the sentences of `line` that name a command, keep the rest.

    Sentence-level, and the choice was between three:

    - Hold the whole message and nudge. That is the better move where it is
      available, so it IS made first: `claims.command_syntax` runs in the chat
      and patrol ladders. It is not available here. `strip_markdown` is a pure
      function on the last seam before Signal, with no model to ask and no way
      to tell a page carrying one bad sentence from a page that is nothing but
      one, and holding the whole message would suppress real news along with
      the hand-off (a guard that can suppress a report is a
      bug).
    - Drop the whole line, which is what the line-anchored guard does. Correct
      when the line IS the command; wrong mid-sentence, where the command
      shares its line with everything else the message says.
    - Cut only the command span. Rejected: where a command ENDS is guesswork
      ("...status harness-webhook.service on the VM for current
      state"), and a mangled half-sentence reads as intended text, which is
      worse than a missing one.

    The cost is real and stays: a sentence that carries the news AND the
    command ("the server disk is almost full, please check df -h / on the
    server") loses the news with it. That is why
    the nudge runs first, and why the seams that may not go quiet carry a floor
    (`chat._EMPTY_AFTER_STRIP_REPLY`,
    `notify_flush`'s floor text); patrol, advise and the security judge are
    allowed to say nothing.
    """
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(line)
        if not _names_an_invocation(sentence)
    ]
    return " ".join(part for part in kept if part.strip()).strip()


def _no_em_dashes(line: str) -> str:
    """Rewrite em dashes as the punctuation the house style uses (soul.md rule
    5): a comma, except between two numbers, where the dash is a range."""
    line = _EM_DASH_RANGE_RE.sub("-", line)
    line = _EM_DASH_TRAILING_RE.sub("", line)
    return _EM_DASH_RE.sub(", ", line)


def _nearest_text(lines: list[str | None], start: int, step: int) -> int | None:
    """Index of the nearest kept, non-blank line from `start` in direction
    `step`, skipping blank lines and other dropped ones; None at the edge."""
    index = start + step
    while 0 <= index < len(lines):
        line = lines[index]
        if line is not None and line.strip():
            return index
        index += step
    return None


def _orphaned_steps(lines: list[str | None], trimmed: set[int]) -> set[int]:
    """The kept lines that only made sense next to a command that was dropped.

    `lines` holds None where a whole line was dropped as a command, and
    `trimmed` the lines that lost a command sentence but kept the rest. Before a
    dropped line, a lead-in ending in a colon is orphaned; after a dropped or
    trimmed one, a "Then ..." or "Also ..." step is."""
    orphaned: set[int] = set()
    for index, line in enumerate(lines):
        if line is None:
            before = _nearest_text(lines, index, -1)
            if before is not None and _LEAD_IN_RE.search(lines[before] or ""):
                orphaned.add(before)
        if line is None or index in trimmed:
            after = _nearest_text(lines, index, 1)
            if after is not None and _FOLLOW_ON_RE.match(lines[after] or ""):
                orphaned.add(after)
    return orphaned


def _one_blank_between(lines: list[str]) -> list[str]:
    """Collapse each run of blank lines to one, so a dropped line never leaves
    a double gap where the blank lines either side of it both survive."""
    collapsed: list[str] = []
    for line in lines:
        if not line.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(line)
    return collapsed


def strip_markdown(note: str) -> str:
    """Drop the markdown Signal shows literally (bold/code/strike markers,
    heading and bullet glyphs, horizontal-rule lines) AND any hallucinated
    tool-call markup or fake command lines, then repair the two voice rules
    that are mechanical: no command for the reader to run, no em dashes.

    A command goes with the whole fix step it belonged to: the lead-in that
    introduced it and the "Then ..." that continued it."""
    note = _TAG_RE.sub("", note)  # kill <function_calls>/<invoke ...>/etc.
    out_lines: list[str | None] = []
    trimmed: set[int] = set()
    for line in note.splitlines():
        if re.fullmatch(r"[-*_]{3,}", line.strip()):
            continue
        if _CMD_LINE_RE.match(line):
            out_lines.append(None)  # the model typing a command it can't run
            continue
        if _JSON_CALL_RE.search(line) or _JSON_CMD_RE.search(line):
            out_lines.append(None)  # a JSON tool-call typed as text
            continue
        line = re.sub(r"\*\*|`|~~", "", line)
        line = re.sub(r"^\s*#{1,6}\s+", "", line)
        line = re.sub(r"^(\s*)[-*•\u2014]\s+", r"\1", line)
        line = _no_em_dashes(line)
        # After the markers come off, so a command written in backticks is seen
        # as the command it is. A blank line never matches, so paragraph breaks
        # survive.
        if _names_an_invocation(line):
            line = _drop_command_sentences(line)
            if not line:
                out_lines.append(None)
                continue
            trimmed.add(len(out_lines))
        out_lines.append(line)
    orphaned = _orphaned_steps(out_lines, trimmed)
    kept = [
        line
        for index, line in enumerate(out_lines)
        if line is not None and index not in orphaned
    ]
    return "\n".join(_one_blank_between(kept)).strip()
