"""USD cost of one Anthropic call, the package's single pricing home.

The per-MT numbers below are Anthropic's published list prices for the pinned
model (`anthropic_client.MODEL` = `claude-sonnet-4-6`), checked against
platform.claude.com/docs/en/about-claude/pricing: base input
$3/MTok, output $15/MTok, 5-minute cache write $3.75/MTok (1.25x base input),
cache read $0.30/MTok (0.1x base input). That page states "All prices are in
USD".

Every euro-named field downstream (`budget.charge`, `budget.snapshot`,
`OPENCLAW_DAILY_CAP_EUR`) is in fact counting USD, so a cap set there is in
dollars per day. The fix is the name, not a conversion: an exchange rate hardcoded here would go
stale and become a second wrong number.

FAILURE POLICY: pure arithmetic, no I/O, nothing to fail.
"""
from __future__ import annotations

# Per-MT list price in USD for Sonnet 4.6 (the same figures the dashkit.ai cost
# map carries; keep the two in sync when the pinned model changes).
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0
# Prompt-caching multipliers on the input rate (Anthropic standard): a 5-min
# cache WRITE costs 1.25x, a cache READ costs 0.1x. With caching on, the
# response splits input into plain `input_tokens` (uncached), plus
# `cache_creation_input_tokens` (write) and `cache_read_input_tokens` (read);
# counting all three keeps the daily budget honest.
CACHE_WRITE_COST_PER_M = INPUT_COST_PER_M * 1.25
CACHE_READ_COST_PER_M = INPUT_COST_PER_M * 0.1


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """What one call's token usage costs at Anthropic's USD list price."""
    return (
        input_tokens * INPUT_COST_PER_M / 1_000_000
        + cache_write_tokens * CACHE_WRITE_COST_PER_M / 1_000_000
        + cache_read_tokens * CACHE_READ_COST_PER_M / 1_000_000
        + output_tokens * OUTPUT_COST_PER_M / 1_000_000
    )


# The old, wrong name for the same USD number. Callers still import it
# (`shared/__init__.py`), so it stays until they are renamed with the rest of the euro layers. New code calls
# `cost_usd`.
cost_eur = cost_usd
