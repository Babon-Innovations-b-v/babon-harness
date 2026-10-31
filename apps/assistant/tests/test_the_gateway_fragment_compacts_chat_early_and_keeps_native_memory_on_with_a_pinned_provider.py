"""The gateway fragment compacts the assistant's chat early and keeps native memory on.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`. The assistant's main chat session
(`agent:main:main`) can run for weeks without one compaction and re-read
hundreds of thousands of tokens on every reply, because safeguard compaction
only fires at the model window minus a reserve, and `claude-opus-5` has a 1M
window. Condense early rather than reset.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Read off a
running gateway (OpenClaw 2026.9.1). There is no threshold key:
usage-based maintenance blocks at "the active model window minus the selected
compaction reserve" (upstream OpenClaw's `docs/reference/session-management-compaction.md`), the
window is `models.providers.<p>.models[].contextTokens` when authored
(`resolveContextTokensForModelFromCache`), and the reserve floor is
`DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR = 2e4`. The fixed prompt alone
(system prompt, injected files, tool schemas) can exceed 60k tokens on a fresh
cron run, so a 60k total trigger would compact every turn. The fixed prompt is
therefore held to a budget of 20,000 (`tools.deny`, no
skills, shorter door definitions), and the trigger is 60k of conversation on
top of that budget: 100,000 - 20,000 = 80,000.
`keepRecentTokens` 20,000 is the verbatim tail kept. No embedding key is
assumed on the host, so memory search is pinned to `provider: "none"`, upstream's explicit FTS-only mode, with no
fallback, so it cannot silently flip to OpenAI embeddings.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment


_UPSTREAM_RESERVE_FLOOR = 20_000
_FIXED_PROMPT_BUDGET = 20_000


def _fragment() -> dict:
    """The fragment as step 68 sends it."""
    return fragment.render_config_patch()


def _opus_cap() -> int:
    """The authored context cap for the model the assistant's chat runs on."""
    models = _fragment()["models"]["providers"]["anthropic"]["models"]
    (opus,) = [model for model in models if model["id"] == "claude-opus-5"]
    return opus["contextTokens"]


def test_compaction_fires_at_about_sixty_thousand_tokens_of_conversation() -> None:
    """The trigger sits about 60k above the fixed prompt, nowhere near 1M."""
    trigger = _opus_cap() - _UPSTREAM_RESERVE_FLOOR
    assert trigger == 80_000
    assert 50_000 <= trigger - _FIXED_PROMPT_BUDGET <= 70_000


def test_compaction_keeps_the_last_twenty_thousand_tokens_verbatim() -> None:
    """The recent tail survives compaction word for word."""
    assert _fragment()["agents"]["defaults"]["compaction"]["keepRecentTokens"] == 20_000


def test_memory_is_flushed_before_compaction() -> None:
    """Notes land in memory/YYYY-MM-DD.md before older turns are summarised."""
    assert _fragment()["agents"]["defaults"]["compaction"]["memoryFlush"]["enabled"] is True


def test_dreaming_is_off() -> None:
    """The nightly sweep can promote nothing and its diary can invent checks
    that never ran, so it stays off until upstream fixes both."""
    dreaming = _fragment()["plugins"]["entries"]["memory-core"]["config"]["dreaming"]
    assert dreaming["enabled"] is False


def test_memory_search_is_on_and_pinned_to_keyword_only() -> None:
    """Search answers from FTS and cannot fall over to an embedding provider."""
    search = _fragment()["memory"]["search"]
    assert search == {"enabled": True, "provider": "none", "fallback": "none"}
