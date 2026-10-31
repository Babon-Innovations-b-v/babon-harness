"""Thin Anthropic SDK wrapper for openclaw's LLM loops.

Why not reuse `dashkit.ai.call_claude` (`lib/dashkit/ai/call_claude.py`)?
- That wrapper logs each call into a per-domain `<x>_ai_calls` Postgres
  table, requires a `conn` arg, and doesn't expose tool-use.
- Openclaw triage needs tool-use, no Postgres dependency at LLM-call
  time, and the cost-accounting goes through `shared.budget` +
  `shared.anthropic_cost` instead.

Single public callable: `create_message(system, messages, tools)`.
Returns the raw Anthropic Message object so the caller can dispatch on
`stop_reason` (`end_turn` vs `tool_use`).

FAILURE POLICY: fail-closed loud. A missing `ANTHROPIC_API_KEY`
raises `RuntimeError` at call time; `anthropic.APIError` propagates to
the LLM loops, which degrade per their own policy (triage → page-raw,
chat → terse error reply).
"""
from __future__ import annotations

import os
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4000


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing: set it in the vault and let the "
            "next deploy cycle write it to the environment file."
        )
    return anthropic.Anthropic(api_key=api_key)


_CACHE = {"type": "ephemeral"}


def create_message(
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> anthropic.types.Message:
    """One metered Anthropic call, with prompt caching on the STATIC prefix.

    Every loop re-sends the same large system prompt and ~25 tool definitions on
    each tool-use iteration; uncached that is paid in full every time. Two cache
    breakpoints fix it: one on the last tool (caches the whole tool list, which
    is identical across every loop and call) and one on the system block (caches
    tools + system, identical across the iterations of one loop). Iterations 2+
    of a tool loop, and any call within the 5-min window, read the prefix at
    ~0.1x instead of re-paying it. Cache tokens are billed back in
    `anthropic_cost.cost_eur` (see brain), so the budget stays honest.
    """
    system_blocks = [{"type": "text", "text": system, "cache_control": _CACHE}]
    cached_tools = tools
    if tools:
        # Copy so the shared TOOL_DEFINITIONS list is never mutated.
        cached_tools = [*tools[:-1], {**tools[-1], "cache_control": _CACHE}]
    return _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=messages,
        tools=cached_tools,
    )
