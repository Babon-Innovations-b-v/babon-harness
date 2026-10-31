"""dashkit.ai: the single LLM metering seam for every dashboard.

Every Claude call in the dashkit ecosystem goes through ``call_claude``
so every token lands in a ``{domain}_ai_calls`` row. Bypassing it means
no cost log. Model and max_tokens defaults live in the shared
``dashkit_ai_config`` table, read at call time.

Module map (one public callable per file):

    call_claude.py            call_claude(...), the metered Claude API call
    ensure_ai_calls_table.py  ensure_ai_calls_table(conn, table), lazy table create
    log_ai_call.py            log_ai_call(conn, table, ...), one accounting row
    _config.py                dashkit_ai_config read (model/max_tokens)
    _extract_json.py          fence-tolerant JSON extraction from model output

FAILURE POLICY: the Claude call itself converts API errors to an
``{"error": ...}`` return value (callers branch, never except). The
``*_ai_calls`` accounting is best-effort: a broken cost log must never
break the feature making the call; every swallow is logged at WARNING.
"""
from __future__ import annotations

from dashkit.ai.call_claude import call_claude
from dashkit.ai.ensure_ai_calls_table import ensure_ai_calls_table
from dashkit.ai.log_ai_call import log_ai_call

__all__ = [
    "call_claude",
    "ensure_ai_calls_table",
    "log_ai_call",
]
