"""Fence-tolerant JSON extraction from Claude responses.

Internal to dashkit.ai: only ``call_claude(expect_json=True)`` uses it.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _extract_json(text: str) -> Any:
    """Extract JSON from a Claude response, tolerating markdown fences.

    Returns the parsed value or None on any failure.
    """
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Candidate cascade, not a swallow: a parse miss here just falls through to the next
            # extraction strategy; total failure is the documented
            # None return.
            pass

    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            # Candidate cascade (see above): fall through to the
            # brace-scan strategy.
            pass

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for idx in range(start, len(text)):
            if text[idx] == start_char:
                depth += 1
            elif text[idx] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : idx + 1])
                    except json.JSONDecodeError:
                        break
    return None
