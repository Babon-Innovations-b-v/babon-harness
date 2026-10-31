"""MCP stdio server for the repository's code index: search_graph, query_graph, search_code.

WHAT. A Model Context Protocol server over stdin and stdout, written with the
Python standard library alone, so a fresh clone on a box with ``python3`` and
nothing installed can start it. Each tool call goes through ``cbm_index.ready``
(the first question on a box installs the pinned binary and builds the index;
a question after a new commit brings the index up to it) and then through
``cbm_index.ask``, one call to the pinned binary's cli. The arguments are
upstream's own; ``project`` defaults to this repository's.

WHY NOT THE TOOL'S OWN SERVER. codebase-memory-mcp allows one daemon version per
user account. A long-running server from one repository refuses every other
repository's build, and it keeps a watcher rewriting the index under readers.
Through the cli nothing outlives the call, and this process ends when the
session closes stdin.

Registered in ``.mcp.json`` as ``{"command": "python3", "args":
[".claude/index/server.py"]}``. A repository with its own index server that
already serves these three tools does not register this one too.

FAILURE POLICY: reports, never raises. A failed call answers ``isError`` with
the cause and the one command that fixes it; a malformed message gets a
JSON-RPC error and the server keeps reading.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cbm_index  # noqa: E402 - the sibling module, found through the line above

#: The protocol version answered when the client asks for none.
_PROTOCOL = "2025-06-18"


def _schema(required: list[str], **properties: str) -> dict:
    """A JSON schema of named arguments, each ``name="type: what it is"``."""
    shaped = {}
    for name, spec in properties.items():
        kind, _, what = spec.partition(": ")
        shaped[name] = ({"type": "array", "items": {"type": "string"}, "description": what}
                        if kind == "list" else {"type": kind, "description": what})
    return {"type": "object", "properties": shaped, "required": required,
            "additionalProperties": True}


_PROJECT = "string: the index's project; defaults to this repository"
_FORMAT = "string: tree (default, compact) or json"

#: The tools, as ``tools/list`` describes them. Names are upstream's.
TOOLS = {
    "search_graph": {
        "description": (
            "Find symbols (functions, classes, methods, files, sections) in the "
            "code graph by name, label, qualified name or file. For a bare symbol "
            "name. A `query` (full text) discards every filter but file_pattern, "
            "limit and offset; for a markdown heading pass label='Section' with "
            "file_pattern and name_pattern and no query."),
        "inputSchema": _schema(
            [], project=_PROJECT, query="string: full-text search over names",
            label="string: Function, Class, Method, File, Section, ...",
            name_pattern="string: regex on the name",
            qn_pattern="string: regex on the qualified name",
            file_pattern="string: glob on the file path",
            relationship="string: only nodes with this edge type",
            limit="integer: rows to return", offset="integer: rows to skip",
            format=_FORMAT),
    },
    "query_graph": {
        "description": (
            "One Cypher query over the code graph: the cheapest way to one fact "
            "(who calls this, what imports this file, is this dead). A malformed "
            "query floods rather than failing: write -[:TYPE]-> or -[]->, never "
            "-->; no second MATCH after a WITH. Edge types include CALLS, "
            "IMPORTS, DEFINES, CONTAINS_FILE."),
        "inputSchema": _schema(
            ["query"], query="string: the Cypher query", project=_PROJECT,
            max_rows="integer: rows to return", offset="integer: rows to skip",
            format=_FORMAT),
    },
    "search_code": {
        "description": (
            "Literal or regex text search over the indexed files, each match "
            "with the symbol it sits in."),
        "inputSchema": _schema(
            ["pattern"], pattern="string: the text or regex", project=_PROJECT,
            file_pattern="string: glob on the file path",
            regex="boolean: treat pattern as a regex",
            context="integer: lines of context", limit="integer: matches to return",
            format=_FORMAT),
    },
}


def answer(tool: str, arguments: dict) -> dict:
    """One tool's answer: ``ok`` with ``result``, or ``error`` and ``fix``."""
    if not isinstance(tool, str) or tool not in TOOLS:
        return {"ok": False, "error": f"no tool {tool!r}",
                "fix": f"use one of {', '.join(TOOLS)}"}
    if arguments is not None and not isinstance(arguments, dict):
        return {"ok": False, "error": f"arguments must be an object, got {arguments!r:.80}",
                "fix": "pass the tool's arguments as a JSON object of named values"}
    place = cbm_index.ready(cbm_index.REPO)
    if "error" in place:
        return {"ok": False, **place}
    given = dict(arguments or {})
    given.setdefault("project", place["project"])
    result = cbm_index.ask(tool, given)
    for key in ("worktree", "rebuilt"):
        if place.get(key):
            result[key] = place[key]
    return result


def _as_text(result: dict) -> str:
    """The answer as the text a model reads: the tool's own words, then any note."""
    if not result.get("ok"):
        return f"error: {result.get('error')}\nfix: {result.get('fix')}"
    body = result["result"]
    text = body if isinstance(body, str) else json.dumps(body)
    notes = []
    if result.get("rebuilt"):
        notes.append("the index was built or brought up to this commit for this call")
    if result.get("worktree"):
        notes.append(result["worktree"])
    return text + "".join(f"\n[index] {note}" for note in notes)


def _initialized(params: dict) -> dict:
    """The ``initialize`` result: who this is and that it serves tools."""
    return {"protocolVersion": params.get("protocolVersion") or _PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "index", "version": "1"}}


def _called(params: dict) -> dict:
    """The ``tools/call`` result for one call."""
    result = answer(params.get("name", ""), params.get("arguments"))
    return {"content": [{"type": "text", "text": _as_text(result)}],
            "isError": not result.get("ok")}


def respond(message: dict) -> dict | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32602, "message": "params must be an object"}}
    if method == "initialize":
        result = _initialized(params)
    elif method == "tools/list":
        result = {"tools": [{"name": name, **spec} for name, spec in TOOLS.items()]}
    elif method == "tools/call":
        result = _called(params)
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main() -> int:
    """Read one JSON-RPC message per line until stdin closes; answer each."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError as failed:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": f"parse error: {failed}"}}
        else:
            reply = (respond(message) if isinstance(message, dict) else
                     {"jsonrpc": "2.0", "id": None,
                      "error": {"code": -32600, "message": "a request is one JSON object"}})
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
