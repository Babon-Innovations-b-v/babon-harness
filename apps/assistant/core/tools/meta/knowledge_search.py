"""Read-only `knowledge_search` tool, search the assistant's knowledge base.

One tool over the durable sources of truth: the bible, the ADRs, the assistant's own
changelog, soul, CONTEXT, and every issue. Use it to ground an answer or a
report, or to check whether the assistant actually knows something before stating
it. The index keeps itself fresh (rebuilds when stale).

Tool-module grammar: NAME, DEFINITION, execute. Read-only, lives in the
shared registry.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core import knowledge

NAME = "knowledge_search"

_MAX_LIMIT = 12


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Search your knowledge base: the bible, the ADRs, the knowledge pages, "
        "soul, CONTEXT, every issue and your own notes. Give a short query of key words."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Key words."},
            "limit": {"type": "integer", "description": "Default 6, max 12."},
        },
        "required": ["query"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    query = str(tool_input.get("query", "")).strip()
    if not query:
        return "knowledge_search needs a query."
    limit = min(int(tool_input.get("limit", 6) or 6), _MAX_LIMIT)
    return knowledge.search(query, limit=limit)
