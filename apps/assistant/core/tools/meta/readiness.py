"""Which tools can actually run right now, the readiness table.

An unset `LOKI_URL` would make `loki_query` answer every call with a refusal
string that reads exactly like an empty result. The model
cannot tell "I have no log tool" from "there are no matching logs", and those
two lead to opposite conclusions, so an unset env var quietly became a wrong
diagnosis.

This module makes the difference mechanical:

  * a tool module may declare `REQUIRES: tuple[str, ...]` of env var names;
  * `snapshot()` reports, per tool, whether every required var is set;
  * the registry seam refuses to dispatch an unavailable tool and says so in
    words the model cannot mistake for data;
  * `render()` pastes the unavailable set into the prompt, so the assistant states its
    own gaps instead of guessing around them;
  * `log_table()` prints the table once at pod start, so the gap is visible in
    the logs on the first boot after it appears rather than weeks later.

A tool with no `REQUIRES` is always ready: it needs no configuration, so there
is nothing to be missing. Readiness here is declaration-based (is the config
present), deliberately NOT a live call: pod start must not depend on every
external service answering, and a flapping endpoint must not read as a missing
tool. A live `probe()` per tool is the natural next step and belongs with the
typed-result work in the same PRD.

FAILURE POLICY: Tier-2. Every read is defended; a fault yields an empty block
or a ready verdict, never an exception. A readiness fault must never break a
loop, because the whole point is to stop config problems becoming outages.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("openclaw.tools.readiness")

# Declared on the tool module; absent means "needs no configuration".
REQUIRES_ATTR = "REQUIRES"


@dataclass(frozen=True)
class Readiness:
    """One tool's verdict: ready to run, or unavailable and exactly why."""

    name: str
    ready: bool
    missing: tuple[str, ...]

    @property
    def reason(self) -> str:
        if self.ready:
            return "ready"
        return f"unset: {', '.join(self.missing)}"


def _missing_for(module: object) -> tuple[str, ...]:
    """Env vars a module declares and the environment does not supply."""
    required = getattr(module, REQUIRES_ATTR, ())
    return tuple(var for var in required if not os.environ.get(var, "").strip())


def snapshot(modules: tuple[object, ...]) -> list[Readiness]:
    """Readiness for every tool module, in registry order."""
    table: list[Readiness] = []
    for module in modules:
        try:
            missing = _missing_for(module)
            name = getattr(module, "NAME", module.__class__.__name__)
        except Exception as exc:  # noqa: BLE001, Tier-2: never break the registry
            log.warning("readiness probe failed for %r: %s", module, exc)
            continue
        table.append(Readiness(name=name, ready=not missing, missing=missing))
    return table


def unavailable_reason(table: list[Readiness], name: str) -> str | None:
    """Why `name` cannot run, or None when it can."""
    for entry in table:
        if entry.name == name and not entry.ready:
            return entry.reason
    return None


def render(table: list[Readiness]) -> str:
    """The prompt block naming the tools the assistant cannot use and why.

    Says nothing when everything is ready: a wall of "all fine" is prompt
    weight that teaches nothing, and the failure this guards against is a
    tool being silently absent, not present.
    """
    unavailable = [entry for entry in table if not entry.ready]
    if not unavailable:
        return ""
    lines = [
        "TOOLS YOU CANNOT USE RIGHT NOW, this is missing configuration, not "
        "an empty result. Do not read around it and do not guess what it would "
        "have said; say plainly that the tool is unavailable and name what is "
        "unset:"
    ]
    for entry in unavailable:
        lines.append(f"- {entry.name}: {entry.reason}")
    return "\n".join(lines)


def log_table(table: list[Readiness]) -> None:
    """Log the readiness table once at startup, loudest line last."""
    ready = [entry.name for entry in table if entry.ready]
    unavailable = [entry for entry in table if not entry.ready]
    log.info("tool readiness: %d ready (%s)", len(ready), ", ".join(sorted(ready)))
    for entry in unavailable:
        log.warning("tool UNAVAILABLE: %s, %s", entry.name, entry.reason)
