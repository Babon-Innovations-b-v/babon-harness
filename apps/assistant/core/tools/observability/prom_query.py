"""Read-only `prom_query` tool, a PromQL instant query.

Hits Prometheus's HTTP read API (`/api/v1/query`) via stdlib urllib
(mirrors notify.py's urllib style). The endpoint comes from
`PROM_URL`, normally `http://prometheus:9090` on the compose network, so
the door reaches it without the single sign-on in front of the public host.
An optional `PROM_BEARER` rides along as the Authorization header for a
Prometheus that sits behind one. This is
a read API, it cannot mutate anything. Tool-module grammar: `NAME`,
`DEFINITION`, `execute`; output bounded by `text.truncate`.

THREE EMPTY ANSWERS ARE NOT ONE. Prometheus answers an empty
vector both for a series that exists but has no current sample and for a
metric name nothing has ever exported, so a guessed metric name reads as a
dark subsystem while the real name has a value. So when a
query comes back empty, the bare metric names in it are checked against
`/api/v1/label/__name__/values`: a name Prometheus does not know is a FAILED
result naming the closest real names, and a known name that matched nothing
says so and says it is not a health statement. A real zero is a series with
value 0 and is passed through untouched.

FAILURE POLICY: HTTP/URL errors and a Prometheus `status: error` body return
`result.failed`, so they never read as an answer; unset endpoint degrades to
`result.unavailable`. If the name lookup itself fails, the empty answer is
returned saying existence could not be checked, never refused.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.tools.prom_query")

NAME = "prom_query"

_PROM_ENV = "PROM_URL"
# Readiness declaration, no endpoint, no tool.
REQUIRES = (_PROM_ENV,)


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "A PromQL instant query against Prometheus, e.g. "
        "scw_estimated_monthly_eur, ops_secret_age_days, up. An unknown metric "
        "name is refused with the closest real names; an empty answer is not an "
        "outage."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "PromQL, e.g. 'max(ops_secret_age_days)'.",
            },
        },
        "required": ["query"],
    },
}


def _get_json(url: str) -> Any:
    """GET a URL and return parsed JSON. Read-only by construction."""
    headers = {"Accept": "application/json"}
    bearer = os.environ.get("PROM_BEARER", "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


# Words in PromQL that look like metric names but are not: keywords, set and
# vector-matching operators, and the bare constants.
_KEYWORDS = frozenset({
    "and", "or", "unless", "by", "without", "on", "ignoring", "group_left",
    "group_right", "bool", "offset", "start", "end", "inf", "nan",
})
_STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`')
_BRACED = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")
_LABEL_LIST = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)", re.IGNORECASE
)
_IDENTIFIER = re.compile(r"(?<![\w.:])[a-zA-Z_:][a-zA-Z0-9_:]*(?![\w(]|\s*\()")

# How long the list of every metric name is reused before it is fetched again.
_NAMES_TTL_SECONDS = 600
_names_cache: dict[str, tuple[float, frozenset[str]]] = {}


def metric_names_in(query: str) -> list[str]:
    """The bare metric names a PromQL expression selects, in order of use.

    String literals, label matchers, range brackets and `by (...)`-style
    label lists are blanked first, so a label name is never taken for a
    metric; function names are skipped because a `(` follows them.
    """
    blanked = _STRING_LITERAL.sub(" ", query)
    blanked = _LABEL_LIST.sub(" ", blanked)
    while _BRACED.search(blanked):
        blanked = _BRACED.sub(" ", blanked)
    names: list[str] = []
    for match in _IDENTIFIER.finditer(blanked):
        name = match.group(0)
        if name.lower() not in _KEYWORDS and name not in names:
            names.append(name)
    return names


def _known_metric_names(base_url: str) -> frozenset[str]:
    """Every metric name Prometheus holds, cached for `_NAMES_TTL_SECONDS`."""
    cached = _names_cache.get(base_url)
    if cached is not None and time.monotonic() - cached[0] < _NAMES_TTL_SECONDS:
        return cached[1]
    body = _get_json(f"{base_url}/api/v1/label/__name__/values")
    names = frozenset(body.get("data") or ())
    _names_cache[base_url] = (time.monotonic(), names)
    return names


def _is_empty(data: Any) -> bool:
    """An instant vector or range matrix with no series at all."""
    return (
        isinstance(data, dict)
        and data.get("resultType") in ("vector", "matrix")
        and not data.get("result")
    )


# Words nearly every metric name carries, which say nothing about what it
# measures. Sharing one of these is not a reason to suggest a name.
_GENERIC_NAME_WORDS = frozenset(
    {"age", "days", "seconds", "timestamp", "total", "last", "ops", "harness"}
)
_HINT_COUNT = 3


def _closest_names(name: str, known: frozenset[str]) -> list[str]:
    """The real names to suggest for a guessed one, best first.

    Names sharing the most distinctive words with the guess come first, the
    closer spelling first among equals, then difflib's spelling matches.
    Spelling alone is not enough: a
    guess such as ops_alert_drill_age_days scores 0.47 against a drill metric
    named like `..._drill_last_success_timestamp_seconds`, under difflib's
    cutoff, and 0.74 against an unrelated ops_secret_age_days, so a
    spelling-only hint names the wrong metric.
    """
    distinctive = set(name.split("_")) - _GENERIC_NAME_WORDS - {""}
    shared = sorted(
        (
            -len(distinctive & set(candidate.split("_"))),
            -difflib.SequenceMatcher(None, name, candidate).ratio(),
            candidate,
        )
        for candidate in known
        if distinctive & set(candidate.split("_"))
    )
    spelled = difflib.get_close_matches(name, sorted(known), n=_HINT_COUNT, cutoff=0.5)
    ranked = [candidate for _, _, candidate in shared] + spelled
    return list(dict.fromkeys(ranked))[:_HINT_COUNT]


def _unknown_names_refusal(unknown: list[str], known: frozenset[str]) -> str:
    """The failure text for names nothing in Prometheus has ever exported."""
    parts = []
    for name in unknown:
        closest = _closest_names(name, known)
        hint = f" Closest real names: {', '.join(closest)}." if closest else ""
        parts.append(
            f"metric '{name}' does not exist in Prometheus (no series under that "
            f"name in its whole retention).{hint}"
        )
    return (
        " ".join(parts)
        + " The name is wrong or nothing exports it; this says nothing about "
        "the service it was meant to measure."
    )


def _explain_empty(base_url: str, query: str, payload: str) -> result.ToolResult:
    """Tell an unknown metric name apart from a known one that matched nothing."""
    names = metric_names_in(query)
    if not names:
        return result.ok(NAME, payload)
    try:
        known = _known_metric_names(base_url)
    except (HTTPError, URLError, ValueError) as exc:
        log.warning("prom_query name lookup failed: %s", exc)
        return result.ok(
            NAME,
            f"{payload}\nNo series matched, and whether {', '.join(names)} exist "
            f"could not be checked ({exc}). Not a statement about health.",
        )
    if not known:
        return result.ok(
            NAME,
            f"{payload}\nNo series matched, and Prometheus listed no metric names "
            f"at all, so whether {', '.join(names)} exist could not be checked. "
            "Not a statement about health.",
        )
    unknown = [name for name in names if name not in known]
    if unknown:
        return result.failed(NAME, _unknown_names_refusal(unknown, known))
    return result.ok(
        NAME,
        f"{payload}\nNo series matched. {', '.join(names)} exist in Prometheus, "
        "so either no current sample is being scraped or the filters exclude "
        "every series. This is not a statement about health, and not a zero.",
    )


def execute(tool_input: dict[str, Any]) -> result.ToolResult:
    base_url = os.environ.get(_PROM_ENV, "").rstrip("/")
    if not base_url:
        return result.unavailable(NAME, "prom_query tool not configured (PROM_URL unset)")

    query = str(tool_input.get("query", ""))
    params = urllib.parse.urlencode({"query": query})
    url = f"{base_url}/api/v1/query?{params}"
    try:
        body = _get_json(url)
    except HTTPError as exc:
        log.warning("prom_query HTTP %d", exc.code)
        return result.failed(NAME, f"prom query failed: HTTP {exc.code}, {exc.read().decode()[:300]}")
    except URLError as exc:
        log.warning("prom_query failed: %s", exc)
        return result.failed(NAME, f"prom query failed: {exc}")
    if isinstance(body, dict) and body.get("status") == "error":
        return result.failed(NAME, f"prom query failed: {body.get('errorType')}: {body.get('error')}")
    data = body.get("data", body) if isinstance(body, dict) else body
    payload = truncate(json.dumps(data, indent=2))
    if _is_empty(data):
        return _explain_empty(base_url, query, payload)
    return result.ok(NAME, payload)
