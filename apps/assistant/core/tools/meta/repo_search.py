"""Read-only `repo_search` tool: the assistant reads the repository's written
documents by their words.

The image carries the repository's markdown (the bible, the ADRs, the
overlays, the glossary, the minutes and whatever the owner keeps under
`business/`) at REPO_ROOT, default `/app`, exactly as of the commit the image
was built from. This tool searches it and returns whole passages.

**How it differs from the two neighbouring tools**, because three search tools
that overlap is worse than one that is vague:

``bible``            one file, `docs/bible.md`, by chapter. Use it when you
                     know the answer is the bible's.
``knowledge_search`` the assistant's own knowledge base: its knowledge pages,
                     its notes and the issues, kept fresh between deploys.
``repo_search``      every markdown file in the repository as of this image,
                     matched on what the documents **say**.

Two calls, and the second is the point: search finds the passage, read returns
the whole document, so an answer never has to stop at a snippet.

FAILURE POLICY: never raises. A missing tree comes back as a sentence naming
the problem, because this container holds no checkout and cannot fetch one;
the remedy is a deploy, and saying so is more useful than an empty answer.
Output is bounded by `text.truncate`.
"""
from __future__ import annotations

import os
import pathlib
import re
from typing import Any

from apps.assistant.core.tools.meta.text import truncate

NAME = "repo_search"

_ROOT_ENV = "REPO_ROOT"
_DEFAULT_ROOT = "/app"

#: Directories never searched: dependencies, build output and VCS internals.
_SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "dist", "build"})

#: Rows a search returns. Small, because each carries a snippet and the whole
#: result is capped anyway; a longer list would be cut mid-row.
_ROWS = 6

#: Characters of one document returned whole by a read.
_READ = 6000

_SNIPPET = 240

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Search the repository's written documents by content: the bible, "
        "ADRs, overlays, the glossary, minutes and business pages. `search` "
        "finds passages; `read` with a result id returns the document."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "Words, e.g. 'backup retention'.",
            },
            "read": {
                "type": "string",
                "description": "A result id, e.g. 'docs/bible.md'.",
            },
        },
    },
}


def _root() -> pathlib.Path:
    return pathlib.Path(os.environ.get(_ROOT_ENV, _DEFAULT_ROOT))


def _documents(root: pathlib.Path) -> list[pathlib.Path]:
    """Every markdown file under `root`, skipping dependency and VCS trees."""
    found: list[pathlib.Path] = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in _SKIP_DIRS)
        found.extend(pathlib.Path(directory) / name for name in sorted(files) if name.endswith(".md"))
    return found


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) pairs, split on markdown headings."""
    parts = re.split(r"^(#{1,4}\s+.+)$", text, flags=re.MULTILINE)
    sections = [("", parts[0])] if parts[0].strip() else []
    for index in range(1, len(parts), 2):
        body = parts[index + 1] if index + 1 < len(parts) else ""
        sections.append((parts[index].lstrip("# ").strip(), body))
    return sections


def _score(words: list[str], blob: str) -> int:
    """How many of the query words the passage carries, weighted by count."""
    lowered = blob.lower()
    hits = [lowered.count(word) for word in words]
    if not any(hits):
        return 0
    return sum(1 for hit in hits if hit) * 100 + sum(hits)


def _snippet(words: list[str], body: str) -> str:
    flat = " ".join(body.split())
    lowered = flat.lower()
    first = min((lowered.find(word) for word in words if word in lowered), default=0)
    start = max(0, first - _SNIPPET // 3)
    return flat[start:start + _SNIPPET]


def _search(query: str) -> str:
    root = _root()
    if not root.is_dir():
        return f"the repository tree is not in this image at {root}; the remedy is a deploy."
    words = [word for word in re.findall(r"\w+", query.lower()) if len(word) > 1]
    if not words:
        return "repo_search needs words to search for."
    scored: list[tuple[int, str, str, str]] = []
    for path in _documents(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ref = str(path.relative_to(root))
        for heading, body in _sections(text):
            score = _score(words, f"{heading} {body}")
            if score:
                scored.append((score, ref, heading, body))
    if not scored:
        return f"nothing in the repository's documents mentions {query!r}."
    scored.sort(key=lambda row: (-row[0], row[1]))
    lines = [
        f"{ref}{' > ' + heading if heading else ''}: {_snippet(words, body)}"
        for _score_value, ref, heading, body in scored[:_ROWS]
    ]
    return truncate("\n".join(lines) + "\n(read a document with read=<path>)")


def _read(ref: str) -> str:
    root = _root().resolve()
    target = (root / ref.split(" > ")[0].strip()).resolve()
    if root not in target.parents or not target.is_file():
        return f"no document {ref!r} in the repository."
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > _READ:
        text = text[:_READ] + f"\n[cut at {_READ} characters of {len(text)}]"
    return truncate(text)


def execute(tool_input: dict[str, Any]) -> str:
    """Search or read; never raises."""
    try:
        ref = str(tool_input.get("read") or "").strip()
        if ref:
            return _read(ref)
        return _search(str(tool_input.get("search") or "").strip())
    except Exception as failed:  # noqa: BLE001 - reported, never raised
        return f"repo_search could not answer that: {failed}"
