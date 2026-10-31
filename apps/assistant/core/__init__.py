"""Openclaw core, the deep modules and their state.

Module map (each deep-module file is named after its one public
callable, so the seam re-exports the MODULES, re-binding the
callables here would shadow the identically-named submodules):

    triage.py       triage(alert) -> TriageResult; bounded Anthropic
                    tool-use loop, decision tree (silent/enrich/page-raw)
    compact.py      compact_week() -> str | None; fold a week of raw
                    memory into one durable summary
    principles.py   render(), HOW openclaw works (seed + taught rules)
    journal.py      render(), WHAT openclaw knows (compacts + notes)
    awareness.py    render(), the current picture from local state
    people.py       identify()/render(), who a sender is + their style
                    (SIGNAL_PEOPLE registry)
    voice.py        render(), the ONE register every human-facing
                    message uses (no banners, one flowing thread)
    outbound.py     remember_sent(subject, body), outbound is memory
    tools/          the LLM tool registry (read-only surface)
    state/          SQLite table adapters (audit, dedup, suppression,
                    budget counter, chat history, journal, compacts)
    limits.py       shared hard caps of the LLM loops
                    (LLM_MAX_ITERATIONS, SIGNAL_MAX_CHARS)

Signature types ride with their callables and
ARE re-exported flat: `Alert`, `TriageResult`, `TriageDecision`.

LAZY SEAM: the re-exports resolve on first attribute access
(PEP 562 `__getattr__`), so importing anything under this package no
longer executes the LLM loops. Importing them eagerly here pulled the
Anthropic SDK into every consumer, including the pure-CalDAV leaves
under `tools/agenda/`, which a laptop-side tool imports without the SDK
installed. Same rule the tools layer already applies to `psycopg2` and
`kubernetes`: the heavy driver is imported where it is used, not where
the package is named. `from ... core import state` still works and is
still the documented way in.

FAILURE POLICY: per submodule, the LLM loops (triage/compact) and tools are Tier-2 degrade-never-drop; state is Tier-1
fail-loud. See each docstring.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from apps.assistant.core.limits import LLM_MAX_ITERATIONS, SIGNAL_MAX_CHARS

if TYPE_CHECKING:  # editors and type checkers see the flat surface
    from apps.assistant.core import (
        awareness,
        brain,
        compact,
        journal,
        meeting_reminders,
        outbound,
        people,
        principles,
        self_context,
        state,
        tools,
        triage,
        voice,
    )
    from apps.assistant.core.brain import LoopOutcome
    from apps.assistant.core.triage import Alert, TriageDecision, TriageResult

_SUBMODULES = frozenset(
    {
        "awareness",
        "brain",
        "compact",
        "journal",
        "meeting_reminders",
        "notulen",
        "outbound",
        "people",
        "principles",
        "roads",
        "self_context",
        "state",
        "tools",
        "triage",
        "voice",
    }
)

# flat signature type -> the submodule it rides with
_FLAT_TYPES = {
    "Alert": "triage",
    "LoopOutcome": "brain",
    "TriageDecision": "triage",
    "TriageResult": "triage",
}


def __getattr__(name: str) -> Any:
    """Resolve a re-export on first access, importing nothing before then."""
    if name in _SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    if name in _FLAT_TYPES:
        return getattr(importlib.import_module(f"{__name__}.{_FLAT_TYPES[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)

__all__ = [
    "Alert",
    "LLM_MAX_ITERATIONS",
    "LoopOutcome",
    "SIGNAL_MAX_CHARS",
    "TriageDecision",
    "TriageResult",
    "awareness",
    "brain",
    "compact",
    "journal",
    "meeting_reminders",
    "outbound",
    "people",
    "principles",
    "self_context",
    "state",
    "tools",
    "triage",
    "voice",
]
