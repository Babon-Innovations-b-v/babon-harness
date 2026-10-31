"""Read-only `loki_query` tool: a LogQL query over a time range.

Hits Loki's HTTP read API (`/loki/api/v1/query_range`) via stdlib urllib. The
endpoint comes from `LOKI_URL`, and the tool is only registered on the
surface when that is set, so a box without Loki never offers the model a tool
that cannot answer. An optional `LOKI_TOKEN` rides along as an `X-Token`
header, the shape a hosted Loki asks for; unset is a
plain GET, which is what a self-hosted Loki wants. This is a read API and
cannot mutate anything. Tool-module grammar: `NAME`, `DEFINITION`, `execute`;
output bounded by `text.truncate`.

Each line is labelled with where it came from: `host/container` when the
shipper sets those labels, else the most telling label Loki carries.

FAILURE POLICY: HTTP/URL errors return as a clear string the LLM reacts to;
an unset endpoint degrades to a "not configured" string naming the variable.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.tools.loki_query")

NAME = "loki_query"

_LOKI_ENV = "LOKI_URL"
# A hosted Loki gates reads on an `X-Token` header; unset = plain GET.
_LOKI_TOKEN_ENV = "LOKI_TOKEN"
# Declared for the readiness table: without the endpoint this tool cannot run
# at all, and that must never look like "no logs matched".
REQUIRES = (_LOKI_ENV,)

# Loki entry cap and default lookback. Keeps one query bounded.
_LOKI_LIMIT = 100
_DEFAULT_LOOKBACK_SECONDS = 3600


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "A LogQL query against Loki over a time range; up to 100 matching "
        "entries, each labelled with the box and container it came from. An "
        "empty answer means nothing matched this selector, not that the system "
        "is quiet: check the selector against the labels Loki carries first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": 'A LogQL query, e.g. \'{container="harness-assistant-1"} |= "Traceback"\'.',
            },
            "lookback_seconds": {
                "type": "integer",
                "description": "Seconds back, default 3600.",
                "default": _DEFAULT_LOOKBACK_SECONDS,
            },
        },
        "required": ["query"],
    },
}


def _get_json(url: str) -> Any:
    """GET a URL and return parsed JSON. Read-only by construction."""
    headers = {"Accept": "application/json"}
    token = os.environ.get(_LOKI_TOKEN_ENV, "")
    if token:
        headers["X-Token"] = token
    request = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def _stream_label(stream: dict[str, Any]) -> str:
    """The shortest label that still says where a line came from.

    Loki repeats the full label set on every stream, which is mostly project
    and region ids that are the same for all of them. The model needs the one
    or two that differ.
    """
    host = stream.get("host")
    if host:
        return f"{host}/{stream.get('container') or stream.get('source') or 'unlabelled'}"
    for key in ("component", "resource_name", "service_name", "instance", "filename"):
        value = stream.get(key)
        if value:
            return str(value)
    return "unlabelled"


def _entry_lines(result: list[dict[str, Any]]) -> list[str]:
    """One readable line per log entry, newest first."""
    entries: list[tuple[str, str, str]] = []
    for stream in result:
        label = _stream_label(stream.get("stream", {}) or {})
        for pair in stream.get("values", []) or []:
            if len(pair) != 2:
                continue
            stamp_ns, message = pair
            try:
                seconds = int(stamp_ns) / 1_000_000_000
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))
            except (TypeError, ValueError):
                stamp = str(stamp_ns)
            entries.append((str(stamp_ns), stamp, f"{stamp} [{label}] {str(message).strip()}"))
    entries.sort(key=lambda entry: entry[0], reverse=True)
    return [line for _, _, line in entries]


def _render(body: Any, query: str, lookback: int) -> str:
    """What the model reads.

    Not `json.dumps(body["data"])`, which would spend the truncate budget on
    the `stats` block and on the label set repeated per stream, and render an
    empty match as `"result": []` buried in JSON. Both matter. The second one
    matters most: a query that matched nothing looks exactly like a quiet,
    healthy system. So an empty match now says in words that it is not a statement
    about health.
    """
    window = f"the last {lookback // 60}m" if lookback >= 60 else f"the last {lookback}s"
    result = (body or {}).get("data", {}).get("result", []) if isinstance(body, dict) else []
    lines = _entry_lines(result if isinstance(result, list) else [])
    if not lines:
        return (
            f"loki {query} over {window}: the query ran and matched no entries. "
            "That is not a statement about health: it means nothing in Loki "
            "matched this selector in this window. Check the selector against "
            "the labels Loki actually carries before reading it as quiet."
        )
    capped = (
        f" This is the {_LOKI_LIMIT}-entry cap, so there are probably more."
        if len(lines) >= _LOKI_LIMIT else ""
    )
    header = f"loki {query} over {window}: {len(lines)} entries, newest first.{capped}"
    return truncate("\n".join([header, *lines]))


def execute(tool_input: dict[str, Any]) -> str:
    base_url = os.environ.get(_LOKI_ENV, "").rstrip("/")
    if not base_url:
        return f"loki_query tool not configured ({_LOKI_ENV} unset)"

    query = str(tool_input.get("query", ""))
    lookback = int(tool_input.get("lookback_seconds", _DEFAULT_LOOKBACK_SECONDS))
    now_ns = time.time_ns()
    start_ns = now_ns - lookback * 1_000_000_000
    params = urllib.parse.urlencode(
        {
            "query": query,
            "start": str(start_ns),
            "end": str(now_ns),
            "limit": str(_LOKI_LIMIT),
            "direction": "backward",
        }
    )
    url = f"{base_url}/loki/api/v1/query_range?{params}"
    try:
        body = _get_json(url)
    except HTTPError as exc:
        log.warning("loki_query HTTP %d", exc.code)
        return f"loki query failed: HTTP {exc.code}, {exc.read().decode()[:300]}"
    except URLError as exc:
        log.warning("loki_query failed: %s", exc)
        return f"loki query failed: {exc}"
    return _render(body, query, lookback)
