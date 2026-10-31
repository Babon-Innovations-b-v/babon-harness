"""The metered Claude API call shared by every dashkit dashboard.

What this module does NOT own: the accounting insert lives in
``log_ai_call.py``; config lives in ``_config.py``; JSON extraction in
``_extract_json.py``.

FAILURE POLICY: API errors (rate limit, context overflow, transport)
are converted to an ``{"error": ..., "detail": ...}`` return value;
callers branch on it, they never need a try/except. The failed call is
still logged to ``{domain}_ai_calls`` so cost dashboards see the miss.
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Any, Optional

import anthropic

from dashkit.ai.log_ai_call import log_ai_call
from dashkit.ai._config import _get_ai_config
from dashkit.ai._extract_json import _extract_json

logger = logging.getLogger("dashkit.ai")

# Cost estimates per 1M tokens (Claude Sonnet pricing; adjust if you
# point dashkit_ai_config at another model).
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0


def call_claude(
    system_prompt: str,
    user_prompt: str,
    *,
    ai_calls_table: str,
    conn=None,
    expect_json: bool = False,
    model_override: Optional[str] = None,
    max_tokens_override: Optional[int] = None,
    run_id: Optional[str] = None,
    doc_path: Optional[str] = None,
) -> dict[str, Any]:
    """Call the Claude API and return the response.

    Returns ``{content, input_tokens, output_tokens, cost_estimate, model}``.

    Args:
        system_prompt: System message.
        user_prompt: User message.
        ai_calls_table: Per-domain table name for the AI call log
            (e.g. ``"notulen_ai_calls"``).
        conn: Optional psycopg connection (for config + logging). May
            be None: a short-lived connection will be opened just for
            the log row.
        expect_json: If True, attempts to parse the response as JSON
            and adds a ``parsed`` field to the result.
        model_override: Override the model from dashkit_ai_config.
        run_id: Optional UUID to group related calls.
        doc_path: Optional document path for the log row.
    """
    # Auto-detect purpose from the caller's function name.
    try:
        caller_name = sys._getframe(1).f_code.co_name
    except Exception:
        caller_name = "unknown"

    config = _get_ai_config(conn)
    model = model_override or config.get("model", "claude-sonnet-4-6")
    if max_tokens_override is not None:
        max_tokens = max_tokens_override
    else:
        max_tokens = int(config.get("max_tokens", "4000"))

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    prompt_size = len(system_prompt) + len(user_prompt)
    logger.info(
        "Claude API call: model=%s, prompt_chars=%d, max_tokens=%d",
        model, prompt_size, max_tokens,
    )

    started = time.monotonic()
    response = None
    err_type: Optional[str] = None
    err_detail: Optional[str] = None
    try:
        # No `temperature`: the anthropic SDK dropped the sampling
        # parameters in 1.0.0, and the current models reject them anyway.
        # Passing one raises TypeError *before* the request is made, which
        # the `except anthropic.*` chain below cannot catch, so every call
        # through this seam would die at the call site.
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.RateLimitError as exc:
        logger.error("Claude rate limit: %s", exc)
        err_type, err_detail = "rate_limit", str(exc)
    except anthropic.BadRequestError as exc:
        logger.error("Claude bad request (context too long?): %s", exc)
        err_type, err_detail = "context_too_long", str(exc)
    except anthropic.APIError as exc:
        logger.error("Claude API error: %s", exc)
        err_type, err_detail = "api_error", str(exc)

    elapsed = time.monotonic() - started
    duration_ms = int(elapsed * 1000)

    if response is None:
        log_ai_call(
            conn,
            ai_calls_table,
            run_id=run_id,
            purpose=caller_name,
            model=model,
            doc_path=doc_path,
            input_tokens=0,
            output_tokens=0,
            cost_estimate=0.0,
            duration_ms=duration_ms,
            success=False,
            error=f"{err_type}: {err_detail}" if err_type else "unknown_error",
        )
        return {"error": err_type or "unknown_error", "detail": err_detail}

    content_text = ""
    if response.content:
        first = response.content[0]
        content_text = getattr(first, "text", "") or ""
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = (input_tokens / 1_000_000) * INPUT_COST_PER_M + (
        output_tokens / 1_000_000
    ) * OUTPUT_COST_PER_M

    logger.info(
        "Claude response: %d input tokens, %d output tokens, $%.4f, %.1fs",
        input_tokens, output_tokens, cost, elapsed,
    )

    log_ai_call(
        conn,
        ai_calls_table,
        run_id=run_id,
        purpose=caller_name,
        model=model,
        doc_path=doc_path,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_estimate=round(cost, 6),
        duration_ms=duration_ms,
        success=True,
        error=None,
    )

    result: dict[str, Any] = {
        "content": content_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate": round(cost, 4),
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
    }

    if expect_json:
        parsed = _extract_json(content_text)
        if parsed is not None:
            result["parsed"] = parsed
        else:
            result["json_parse_error"] = True
            logger.warning("Failed to parse JSON from Claude response")

    return result
