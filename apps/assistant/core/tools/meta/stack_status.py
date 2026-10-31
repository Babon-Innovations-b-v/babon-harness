"""Read-only `stack_status` tool, the authoritative liveness answer.

Surfaces the stack-liveness monitor's current view to the chat
loop so "is everything alive?" is answered from the registry's recorded
status, not guessed from a kubectl peek. Reads
`state.component_status.get_all()`, groups by the registry's group, and
leads with anything not `up` (the thing the owner actually wants). Read-only:
it reports the sweep's findings, it does not run checks or write.

It closes with the container's own start history from `state.pod_boots`:
the status rows say what is true now and are
overwritten every sweep, so "did the container flap last week" needs the
append-only side, and the cluster drops that within hours.

Tool-module grammar: `NAME`, `DEFINITION`, `execute`. Output bounded by
`text.truncate`.

FAILURE POLICY: errors propagate to the registry's defended Tier-2 catch
(`core.tools.execute`), which feeds them back to the LLM as text.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core import state
from apps.assistant.core.monitor.registry import REGISTRY
from apps.assistant.core.state.component_status import STATUS_UP
from apps.assistant.core.tools.meta.text import truncate

NAME = "stack_status"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Live status of every stack component, anything not up first, then the "
        "assistant container's starts this week and last (new pods versus restarts)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

# How far back the restart line looks. A week, because that is the window
# the question is asked in ("did it flap last week").
BOOT_WINDOW_DAYS = 7

# Map each component name to its registry group, so the report groups the
# recorded rows the same way the registry declares them.
_GROUP_FOR = {component.name: component.group for component in REGISTRY}


# What the count leaves out, said under every headline. The registry holds no
# VM docker container on purpose (they moved to harness_container_up), but a bare
# "ALL UP (N components)" reads as the whole stack, as if it covered the
# containers too.
_SCOPE = (
    "Scope: the monitor registry's components only. The VM's docker containers "
    "(harness-*-1, assistant, assistant-gateway, signal-cli, assistant-whisper) are not in "
    "this count, so it says nothing about them; their liveness is "
    "harness_container_up and harness_container_restarts_total in Prometheus."
)

# How old the newest reading may be before this answer stops meaning anything.
# The sweep runs every SWEEP_INTERVAL_SECONDS, so several missed passes is a
# sweep that has stopped rather than one that is merely between runs.
_STALE_AFTER_S = 15 * 60


def _sweep_age_line(rows: list[dict[str, Any]]) -> str:
    """A line naming the age of the readings, or "" when they are fresh.

    This function is the authoritative liveness answer, so it guards a STALE
    table as well as an empty one. A sweep thread that has died leaves every
    row exactly as it was, and without this line the answer would be ALL UP
    from readings that have stopped moving, in the confident present tense,
    produced by the component whose failure it is supposed to reveal.
    """
    stamps = [str(row.get("last_checked_at") or "") for row in rows]
    newest = max((stamp for stamp in stamps if stamp), default="")
    if not newest:
        return "NOTE: these readings carry no timestamp, so their age is unknown."
    try:
        seen = datetime.fromisoformat(newest)
    except ValueError:
        return f"NOTE: newest reading has an unreadable timestamp ({newest})."
    age = (datetime.now(timezone.utc) - seen).total_seconds()
    if age <= _STALE_AFTER_S:
        return ""
    return (
        f"WARNING: the newest reading here is from {newest}, "
        f"{int(age // 60)} minutes ago. The sweep has stopped, so this is what "
        "was true then, not what is true now. Do not report it as current."
    )


def _render(rows: list[dict[str, Any]]) -> str:
    """Render the status rows: a headline (all up, or what's not up) then
    a grouped per-component listing."""
    if not rows:
        return "stack status: no components checked yet (sweep not run)"

    stale = _sweep_age_line(rows)
    not_up = [row for row in rows if row["status"] != STATUS_UP]
    if not not_up:
        headline = f"ALL UP ({len(rows)} components)"
    else:
        names = ", ".join(f"{row['component']}={row['status']}" for row in not_up)
        headline = f"NOT UP ({len(not_up)}/{len(rows)}): {names}"

    by_group: dict[str, list[str]] = {}
    for row in rows:
        group = _GROUP_FOR.get(row["component"], "other")
        detail = f" ({row['detail']})" if row["detail"] else ""
        by_group.setdefault(group, []).append(
            f"  {row['component']}: {row['status']}{detail}"
        )

    sections = [headline, _SCOPE] if not stale else [headline, _SCOPE, stale]
    for group in sorted(by_group):
        sections.append(f"[{group}]")
        sections.extend(by_group[group])
    return "\n".join(sections)


def _count_starts(starts: list[dict[str, Any]]) -> str:
    """Name one window's starts as the two quantities they are.

    A new pod is a rollout or a reschedule; only a pod name starting again is
    a container restart in place. The bare word "restarts" for the total would
    make a week of rolling deploys read as "a lot of churn"."""
    in_place = sum(1 for start in starts if start["in_place"])
    return f"{len(starts) - in_place} new pods, {in_place} in-place container restarts"


def _render_boot_history() -> str:
    """Render the container's own start history over `BOOT_WINDOW_DAYS`, with the
    window before it, so "was N last time" is read here and never recalled.

    Always names how far back the record itself goes, so a quiet window
    cannot be read as proof of a quiet week: no rows since Monday means
    the container held only if the table was already recording on Monday."""
    first_at = state.pod_boots.first_boot_at()
    if first_at is None:
        return (
            "assistant container starts: nothing recorded yet, the history "
            "starts at the pod's next boot"
        )
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=BOOT_WINDOW_DAYS)
    earlier_cutoff = cutoff - timedelta(days=BOOT_WINDOW_DAYS)
    starts = state.pod_boots.starts_between(cutoff.isoformat(), now.isoformat())
    earlier = state.pod_boots.starts_between(earlier_cutoff.isoformat(), cutoff.isoformat())
    latest = f", latest {starts[-1]['booted_at']} ({starts[-1]['pod']})" if starts else ""
    return (
        f"assistant container starts (last {BOOT_WINDOW_DAYS}d): {_count_starts(starts)}"
        f"{latest}; the {BOOT_WINDOW_DAYS}d before that: {_count_starts(earlier)}. "
        "A new pod is a rollout or reschedule, not a crash. "
        f"Recorded since {first_at}"
    )


def execute(tool_input: dict[str, Any]) -> str:
    rows = state.component_status.get_all()
    return truncate(f"{_render(rows)}\n{_render_boot_history()}")
