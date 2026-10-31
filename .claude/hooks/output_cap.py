#!/usr/bin/env python3
"""PostToolUse hook: a long Bash output goes to a file, and the agent sees a short summary of it with the file's path.

When a Bash call's stdout and stderr together are longer than ``CAP_CHARS``, the whole output is written to
``<OUTPUT_CAP_DIR or $TMPDIR/output-cap>/<session>/<call>.txt`` and the output the model sees is replaced
(``hookSpecificOutput.updatedToolOutput``) by a header with the counts and the file's path, then the JSON's structure
or else the first lines, the error and warning lines and the last lines. Nothing is lost: the file holds every byte.

Left untouched: outputs up to the cap, images, background commands, reads the agent narrowed itself (a pipeline ending
in ``head``, ``tail``, ``sed -n``, ``awk`` with ``NR``, ``grep -m`` or ``-c``, ``wc``), a ``cat`` of a rules file read
whole to follow it (``CLAUDE.md``, ``SKILL.md``, ``soul.md``, ``CONTEXT.md``), a summary not at least ``MIN_SAVING``
shorter, and any command carrying ``FULL_OUTPUT=1``. Claude Code's own limit still applies above 30,000
characters. A failing command fires PostToolUseFailure, which cannot replace output, so it is never capped here.

FAILURE POLICY: fail open. An unreadable payload, an unknown output shape, or a spill file that cannot be written
leaves the output as it was (exit 0, no replacement), so a fault here can only cost tokens, never hide output.
"""

import json
import os
import pathlib
import re
import shlex
import sys
import time

CAP_CHARS = 6000
HEAD_LINES = 25
TAIL_LINES = 25
MATCH_LINES = 20
LINE_CHARS = 200
SECTION_CHARS = 1200
MIN_SAVING = 0.4
FULL_OUTPUT_MARKER = "FULL_OUTPUT=1"
_MATCH = re.compile(r"\b(errors?|traceback|fail(ed|ures?)?|warnings?|exception)\b", re.IGNORECASE)
_NARROWED = re.compile(r"^(head|tail|wc)\b|^sed\s+(-\w+\s+)*-n\b|^awk\b.*\bNR\b|^grep\b.*\s-\w*[mc]\w*\b")
_QUIET = re.compile(r"^(cd|echo|printf|export|set|true|mkdir|rm|mv|cp|touch|sleep)\b|^$")
_RULES_CAT = re.compile(r"\bcat\s+(\S*/)?(CLAUDE|SKILL|soul|CONTEXT)\.md\b")
_WHOLE_CAT = re.compile(r"^cat (?P<path>[^\s*?-]\S*)$")


def _tokens(command):
    """Shell words and operators (quotes respected, newline kept as an operator); None when it does not parse."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _last_stages(command):
    """The last command of each pipeline in a command list, as one string per pipeline, stderr redirects dropped."""
    tokens = _tokens(command)
    if tokens is None:
        return [command]
    stages, current = [], []
    for token in tokens + [";"]:
        if token in (";", "&&", "||", "&", "\n", ";;"):
            stages.append(" ".join(current))
            current = []
        elif token == "|":
            current = []
        else:
            current.append(token)
    return [re.sub(r"\s+2\s+(>&\s+1|>\s+/dev/null)$", "", stage) for stage in stages]


def leave_alone(command):
    """True when the agent asked for this output as it is: the full-output marker, reads it narrowed itself, or a
    rules file (CLAUDE.md overlay, SKILL.md, soul.md, CONTEXT.md) it reads whole to follow."""
    if FULL_OUTPUT_MARKER in command or _RULES_CAT.search(command):
        return True
    printing = [stage for stage in _last_stages(command) if not _QUIET.search(stage)]
    return bool(printing) and all(_NARROWED.search(stage) for stage in printing)


def spill_path(payload):
    """The file this call's full output goes to, unique per session and call."""
    default = pathlib.Path(os.environ.get("TMPDIR") or "/tmp") / "output-cap"
    root = pathlib.Path(os.environ.get("OUTPUT_CAP_DIR") or default)
    session = re.sub(r"[^\w.-]", "_", str(payload.get("session_id") or "session"))
    call = re.sub(r"[^\w.-]", "_", str(payload.get("tool_use_id") or f"call-{time.time_ns()}"))
    return root / session / f"{call}.txt"


def write_spill(path, command, stdout, stderr):
    """Write the command and its whole output to the spill file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"$ {command}\n", stdout]
    if stderr:
        parts += ["\n--- stderr ---\n", stderr]
    path.write_text("".join(parts))


def _clip(line):
    return line if len(line) <= LINE_CHARS else line[:LINE_CHARS] + f" [... {len(line) - LINE_CHARS} more chars]"


def json_outline(text):
    """The structure of a JSON document, a few lines long; None when the text is not JSON."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        document = json.loads(stripped)
    except ValueError:
        return None
    return [f"JSON {_shape(document)}"] + _children(document)


def _shape(value):
    if isinstance(value, dict):
        return f"object, {len(value)} keys"
    if isinstance(value, list):
        return f"array, {len(value)} items"
    if isinstance(value, str):
        return f"string, {len(value)} chars" if len(value) > 60 else json.dumps(value)
    return json.dumps(value)


def _children(document):
    """One line per top-level key (or, for an array, the first item's keys), with its shape."""
    if isinstance(document, dict):
        items = list(document.items())
        lines = [f"  {key}: {_shape(value)}" for key, value in items[:40]]
        return lines + ([f"  ... {len(items) - 40} more keys"] if len(items) > 40 else [])
    if isinstance(document, list) and document and isinstance(document[0], dict):
        return [f"  [0].{key}: {_shape(value)}" for key, value in list(document[0].items())[:40]]
    return []


def _fit(lines, budget):
    """As many of the lines as fit in the budget of characters (at least one), each clipped."""
    taken, used = [], 0
    for line in lines:
        clipped = _clip(line)
        if taken and used + len(clipped) > budget:
            break
        taken.append(clipped)
        used += len(clipped) + 1
    return taken


def text_excerpt(lines):
    """The first lines, the error and warning lines between them and the last lines, within a character budget."""
    head = _fit(lines[:HEAD_LINES], SECTION_CHARS)
    tail = _fit(lines[len(head):][-TAIL_LINES:][::-1], SECTION_CHARS)[::-1]
    middle = range(len(head), len(lines) - len(tail))
    matches = [index for index in middle if _MATCH.search(lines[index])]
    excerpt = [f"--- first {len(head)} lines ---", *head]
    if matches:
        shown = _fit([f"{index + 1}: {lines[index]}" for index in matches[:MATCH_LINES]], SECTION_CHARS)
        excerpt += [f"--- {len(shown)} of {len(matches)} error/warning lines in between (line number: text) ---", *shown]
    if len(middle):
        excerpt.append(f"--- {len(middle):,} lines in between are in the file ---")
    return excerpt + [f"--- last {len(tail)} lines ---", *tail]


def summary(command, stdout, stderr, path):
    """What the model sees instead of the long output."""
    whole = stdout + (("\n" if stdout and not stdout.endswith("\n") else "") + stderr if stderr else "")
    lines = whole.splitlines()
    header = (f"[output cap: {len(lines):,} lines, {len(whole):,} chars; the whole output is in {path}; read the part "
              f"you need with Read (offset, limit), grep or sed -n. Prefix a command with {FULL_OUTPUT_MARKER} to see "
              f"its output in full.]")
    for whole_cat in filter(None, (_WHOLE_CAT.match(stage) for stage in _last_stages(command))):
        header += f"\n[whole-file cat of {whole_cat.group('path')}: read it in ranges with Read (offset, limit) instead.]"
    body = (json_outline(stdout) if not stderr.strip() else None) or text_excerpt(lines)
    return "\n".join([header, *body])


def capped_output(payload):
    """The replacement Bash output, or None when this output stays as it is."""
    if payload.get("tool_name") != "Bash":
        return None
    response = payload.get("tool_response")
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not isinstance(response, dict) or response.get("isImage") or response.get("backgroundTaskId"):
        return None
    stdout, stderr = response.get("stdout"), response.get("stderr") or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str) or len(stdout) + len(stderr) <= CAP_CHARS:
        return None
    if leave_alone(command):
        return None
    path = spill_path(payload)
    text = summary(command, stdout, stderr, path)
    if len(text) > (1 - MIN_SAVING) * (len(stdout) + len(stderr)):
        return None
    write_spill(path, command, stdout, stderr)
    return dict(response, stdout=text, stderr="")


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        output = capped_output(payload)
    except OSError as error:  # the spill file could not be written: keep the output, say why
        print(f"output_cap: output left whole, spill failed: {error}", file=sys.stderr)
        return 0
    if output is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": output}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
