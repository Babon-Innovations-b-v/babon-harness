#!/usr/bin/env python3
"""PreToolUse guard: a new markdown file needs the user's go-ahead.

Reads the Claude Code PreToolUse payload on stdin and blocks creating a ``.md`` that does not exist yet anywhere under
the repo, by ``Write`` or by a Bash redirect (``>``, ``>>``), ``tee``, ``touch`` or ``cp`` with a ``.md``
destination.

Allowed:

- editing an existing ``.md``;
- anything outside the repo (``/tmp``, a job scratch dir), which is where generated pages belong;
- ``mv`` and ``git mv``: a rename leaves the count unchanged (``cp`` adds a file, so it still counts);
- a per-directory ``CLAUDE.md`` overlay, the standing exception: it is the mechanism that loads a directory's rules,
  so a code directory without one is a gap, not a document;
- ``.claude/memory/``: private working notes;
- a file the user asked for: when one of the person's last twenty typed messages in the session transcript names an
  md or markdown file, the creation goes through (tool results do not count, they are the machine talking);
- a path listed in ``.claude/hooks/local/md_allowed.json`` with the user's words and the time, when the repository
  keeps such a list (``[{"path": ..., "words": ..., "at": ...}]``; an entry without words does not count).

Why: every markdown file in a repository run this way is living, read by someone and kept current. A summary file
dropped at a session's end has nobody keeping it current and the next session reads it as truth, so each new file is
the user's decision, not a side effect of a session.

FAILURE POLICY: fail-open. Any parse error, unknown shape or unrelated call exits 0 (allow). Exit 2 + stderr is the
only block path (the harness feeds stderr back to the model as the block reason).
"""

import json
import os
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALLOWED = pathlib.Path(__file__).resolve().parent / "local" / "md_allowed.json"
_MEMORY = _REPO_ROOT / ".claude" / "memory"

# Shell forms that can bring a new file into existence.
_SHELL_TARGETS = (
    re.compile(r">>?\s*(?P<path>[^\s|;&<>()]+\.md)\b", re.IGNORECASE),
    re.compile(r"\btee\s+(?:-a\s+)?(?P<path>[^\s|;&<>()-][^\s|;&<>()]*\.md)\b", re.IGNORECASE),
    re.compile(r"\btouch\s+(?P<path>[^\s|;&<>()]+\.md)\b", re.IGNORECASE),
    re.compile(r"\bcp\s+[^;|&]*?\s(?P<path>[^\s|;&<>()]+\.md)\b", re.IGNORECASE),
)
# A `cd` and a `NAME=value` earlier in the same command change where a relative path lands.
_CD = re.compile(r"(?:^|[;&|\n(])\s*cd\s+(?P<dir>[^\s|;&<>()]+)")
_ASSIGN = re.compile(r"(?:^|[;&|\n(])\s*(?P<name>[A-Za-z_]\w*)=(?P<value>[^\s|;&<>()]+)")

_MESSAGE = (
    "Blocked: creating a new markdown file needs the user's go-ahead (CLAUDE.md, Rules).\n"
    "  would create: {path}\n"
    "Every .md in this repo is living and earns its place, so the count stays minimal.\n"
    "Instead: put it in an existing file, add a section to docs/bible.md, or post it as a\n"
    "comment on the issue it belongs to. ADRs are covered too: offer one in a line and\n"
    "write it after the yes. Generated pages render outside the repo (/tmp or the job\n"
    "scratch dir), which this guard allows.\n"
    "If the file genuinely has to exist, ask the user in this session: a message of theirs\n"
    "naming an md file lets it through."
)

_ASKED_FOR_MARKDOWN = re.compile(r"(?<![\w/])(?:\.md|md|markdown)\b", re.IGNORECASE)
_RECENT_USER_MESSAGES = 20  # a yes holds through a working session; 3 lost one after a night of status messages


def _approved() -> set[pathlib.Path]:
    """The repo paths the user said yes to, from the local allow list; none when it is missing or unreadable."""
    try:
        entries = json.loads(_ALLOWED.read_text())
    except (OSError, ValueError):
        return set()
    return {(_REPO_ROOT / entry["path"]).resolve() for entry in entries if entry.get("words") and entry.get("path")}


def _blocked(raw: str, base: pathlib.Path) -> pathlib.Path | None:
    """The offending path when `raw` names a new .md inside the repo, else None.

    A relative path resolves against `base`, the directory the command writes from, not the repository root: a
    session working in another repository on the same machine, or a command that cd's to scratch first, writes
    outside this tree."""
    if not raw:
        return None
    candidate = base / raw.strip().strip("'\"")  # an absolute path replaces base
    try:
        resolved = candidate.resolve()
        resolved.relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return None  # outside the repo, or unresolvable: not ours to police
    if resolved.exists() or resolved.name == "CLAUDE.md" or resolved.is_relative_to(_MEMORY):
        return None
    if resolved in _approved():
        return None
    return resolved


def _expanded(raw: str, known: dict[str, str]) -> str | None:
    """`raw` with its shell variables filled in (those set earlier in the command first, then the environment), or
    None when one is still unknown: the failure policy says allow."""
    text = raw.strip().strip("'\"")
    for name, value in known.items():
        text = re.sub(r"\$(?:\{%s\}|%s(?!\w))" % (name, name), lambda _match: value, text)
    text = os.path.expanduser(os.path.expandvars(text))
    return None if "$" in text else text


def _shell_candidates(command: str, base: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """Each markdown path a shell command could create, with the directory it lands in. Walks the command in order,
    so a `cd` or a variable counts only for the writes after it; after a `cd` somewhere unknowable, relative paths are
    left unjudged."""
    steps = [(match.start(), "cd", "", match.group("dir")) for match in _CD.finditer(command)]
    steps += [(match.start(), "set", match.group("name"), match.group("value")) for match in _ASSIGN.finditer(command)]
    steps += [(match.start("path"), "path", "", match.group("path"))
              for pattern in _SHELL_TARGETS for match in pattern.finditer(command)]
    known: dict[str, str] = {}
    here: pathlib.Path | None = base
    found: list[tuple[str, pathlib.Path]] = []
    for _, kind, name, text in sorted(steps, key=lambda step: step[0]):
        filled = _expanded(text, known)
        if kind == "set":
            if filled is not None:
                known[name] = filled
        elif kind == "cd":
            here = None if filled is None or filled == "-" or here is None else here / filled
        elif filled is not None and (here is not None or filled.startswith("/")):
            found.append((filled, here or base))
    return found


def _typed_text(line: bytes) -> str | None:
    """The text of one transcript line when it is a message the person typed, else None; tool results are left out."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return None
    message = entry.get("message") or {}
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and not any(
            isinstance(part, dict) and part.get("type") == "tool_result" for part in content):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return None


def _recent_typed_messages(transcript: pathlib.Path, count: int) -> list[str]:
    """The last `count` messages the person typed, oldest first. Reads the transcript from its end in growing chunks,
    never the whole file unless it must: a long session's transcript runs to hundreds of MB, and reading it all took
    seconds a call, so the harness timed the guard out (failing open)."""
    size = transcript.stat().st_size
    chunk = 1 << 18
    with transcript.open("rb") as stream:
        while True:
            start = max(0, size - chunk)
            stream.seek(start)
            lines = stream.read(size - start).split(b"\n")
            if start:
                lines = lines[1:]  # the first line is cut mid-way
            texts = [text for text in map(_typed_text, filter(None, lines)) if text is not None]
            if len(texts) >= count or not start:
                return texts[-count:]
            chunk *= 4


def _user_asked_for_markdown(payload: dict) -> bool:
    """True when one of the person's last few messages names an md or markdown file."""
    transcript = payload.get("transcript_path")
    if not transcript:
        return False
    try:
        recent = _recent_typed_messages(pathlib.Path(transcript), _RECENT_USER_MESSAGES)
    except OSError:
        return False
    return any(_ASKED_FOR_MARKDOWN.search(text) for text in recent)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    base = pathlib.Path(payload.get("cwd") or _REPO_ROOT)
    candidates: list[tuple[str, pathlib.Path]] = []
    if tool == "Write" and str(tool_input.get("file_path", "")).lower().endswith(".md"):
        candidates = [(str(tool_input.get("file_path", "")), base)]
    elif tool == "Bash":
        candidates = _shell_candidates(str(tool_input.get("command", "")), base)
    offenders = [offender for offender in (_blocked(raw, where) for raw, where in candidates) if offender is not None]
    # The transcript is read only for a call that would create a new .md: every other call returns before it.
    if not offenders or _user_asked_for_markdown(payload):
        return 0
    print(_MESSAGE.format(path=offenders[0].relative_to(_REPO_ROOT)), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
