"""Read-only `bible` tool, the assistant reads the project bible, the single source
of truth for how the system is built.

The bible (`docs/bible.md`) is the canonical description of the architecture,
deploy loop and the rules the repository runs by. Giving the assistant a way to
read it turns it from "knows live state" into "understands the system": it can
look up how a component works, what a rule is, or where data lives before it
answers or judges.

The file grows too big to hand the model whole, so this tool is
chapter-aware. Chapters are the `## <slug>` headings (e.g.
`architecture/system-context`, `infra/observability`):
- no arguments -> the table of contents (every chapter slug);
- `chapter` -> that one chapter's text;
- `search` -> the chapters that mention a term, with a snippet.

The bible is baked into the image (`docs/bible.md`, copied in by
`apps/assistant/Dockerfile`) and read from `OPENCLAW_BIBLE_PATH`. Tool-module grammar: `NAME`,
`DEFINITION`, `execute`.

FAILURE POLICY: a missing/unreadable bible returns a clear "not available"
string, never raises; output is bounded by `text.truncate`.
"""
from __future__ import annotations

import os
from typing import Any

from apps.assistant.core.tools.meta.text import truncate

NAME = "bible"

_BIBLE_PATH_ENV = "OPENCLAW_BIBLE_PATH"
_DEFAULT_PATH = "/app/docs/bible.md"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Read the bible, how the system is built. No arguments lists the "
        "chapters; `chapter` reads one (e.g. 'architecture/components'); "
        "`search` finds chapters mentioning a term."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chapter": {
                "type": "string",
                "description": "Chapter slug.",
            },
            "search": {
                "type": "string",
                "description": "Term to find.",
            },
        },
    },
}


def _load() -> str | None:
    path = os.environ.get(_BIBLE_PATH_ENV, _DEFAULT_PATH)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _chapters(text: str) -> list[tuple[str, str]]:
    """Split the bible into (slug, body) on level-2 `## ` headings. The body
    includes the heading line and everything down to the next `## `."""
    chapters: list[tuple[str, str]] = []
    slug: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if slug is not None:
                chapters.append((slug, "\n".join(buffer)))
            slug = line[3:].strip()
            buffer = [line]
        elif slug is not None:
            buffer.append(line)
    if slug is not None:
        chapters.append((slug, "\n".join(buffer)))
    return chapters


def _table_of_contents(chapters: list[tuple[str, str]]) -> str:
    slugs = [slug for slug, _ in chapters]
    return "Bible chapters (read one with chapter=<slug>):\n" + "\n".join(slugs)


def _read_chapter(chapters: list[tuple[str, str]], wanted: str) -> str:
    target = wanted.strip().lower()
    for slug, body in chapters:
        if slug.lower() == target:
            return truncate(body)
    for slug, body in chapters:  # fall back to a substring match
        if target in slug.lower():
            return truncate(body)
    toc = ", ".join(slug for slug, _ in chapters)
    return f"no chapter matching {wanted!r}. Chapters: {toc}"


def _search(chapters: list[tuple[str, str]], term: str) -> str:
    needle = term.strip().lower()
    hits: list[str] = []
    for slug, body in chapters:
        matching = [line.strip() for line in body.splitlines()
                    if needle in line.lower() and not line.startswith("## ")]
        if needle in slug.lower() or matching:
            snippet = matching[0] if matching else "(in chapter title)"
            hits.append(f"{slug}: {snippet}")
    if not hits:
        return f"no bible chapter mentions {term!r}"
    return truncate("Chapters mentioning " + repr(term) + ":\n" + "\n".join(hits))


def execute(tool_input: dict[str, Any]) -> str:
    text = _load()
    if text is None:
        return "bible not available (OPENCLAW_BIBLE_PATH unset or unreadable)"
    chapters = _chapters(text)
    search = str(tool_input.get("search", "")).strip()
    chapter = str(tool_input.get("chapter", "")).strip()
    if search:
        return _search(chapters, search)
    if chapter:
        return _read_chapter(chapters, chapter)
    return _table_of_contents(chapters)
