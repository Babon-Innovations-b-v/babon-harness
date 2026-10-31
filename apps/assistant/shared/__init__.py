"""Cross-gate utilities, auth, Signal dispatch, Anthropic client +
pricing, budget policy.

Module map:
    auth.py              verify(header), shared-secret bearer check
    signal.py            send(subject, body), outbound signal-cli with
                         retry + dead-letter (the container's own send path)
    anthropic_client.py  create_message(...), thin SDK wrapper
    anthropic_cost.py    cost_eur(...), the package's pricing home
    budget/              daily spend cap policy (see its seam)

Per the overlay: no view code here, no triage logic here. Pure helpers
that gates + core call.

LAZY SEAM: the four flat callables resolve on first access, so
naming this package does not import the Anthropic SDK through
`anthropic_client`. `from ... shared import budget` and the other
submodule imports are unchanged.

FAILURE POLICY: per module, auth and the Anthropic client are
fail-closed loud; budget is Tier-1; `signal.send` is the package's one
Tier-2 dead-letter swallow.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # editors and type checkers see the flat surface
    from apps.assistant.shared.anthropic_client import create_message
    from apps.assistant.shared.anthropic_cost import cost_eur
    from apps.assistant.shared.auth import verify
    from apps.assistant.shared.signal import send

# flat callable -> the module that owns it
_FLAT_CALLABLES = {
    "cost_eur": "anthropic_cost",
    "create_message": "anthropic_client",
    "send": "signal",
    "verify": "auth",
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported callable on first access, importing nothing before then."""
    if name in _FLAT_CALLABLES:
        return getattr(importlib.import_module(f"{__name__}.{_FLAT_CALLABLES[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = ["cost_eur", "create_message", "send", "verify"]
