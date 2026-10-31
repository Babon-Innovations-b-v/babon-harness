"""Typed tool results, status, freshness, and the text the model sees.

A bare string from every tool would leave three very different things
indistinguishable to the model and to a test:

  * it ran and found nothing,
  * it ran and the world said no,
  * it never ran because its configuration is missing.

Those lead to opposite conclusions: an unset endpoint answering with a
refusal string reads exactly like an empty result.

`ToolResult` makes the status explicit, and `render()` puts it in front of the
data where the model cannot skim past it. Every observation is also stamped
with the time it was fetched: a model can report a reading taken minutes
earlier as current, and a timestamp per result is the cheapest guard
against that.

Backwards compatible on purpose. A tool may keep returning a plain string and
the seam wraps it as OK; a tool that wants to be precise returns a
`ToolResult`. That lets tools migrate one at a time instead of in one risky sweep. One
exception, because it would make failures read as evidence: a string that opens with the tool's own name followed by "failed" or
"not configured" ("gh issue view failed (rc=1): ...") is the tool reporting it
did not get an answer, and is typed FAILED or UNAVAILABLE, never OK; wrapped
as OK it would read as "an issue no longer exists". Matching on the tool's own name keeps an OK answer that merely mentions a
failure ("last deploy failed at ...") OK.

FAILURE POLICY: pure data plus a string render, nothing here performs IO, so
nothing here can fail. The seam owns the defended dispatch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Ran, produced an answer (including a legitimately empty one).
OK = "ok"
# Ran, and failed: the endpoint errored, the query was rejected, it raised.
FAILED = "failed"
# Never ran: required configuration or credentials are missing.
UNAVAILABLE = "unavailable"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ToolResult:
    """One tool call's outcome, as data rather than prose."""

    tool: str
    status: str = OK
    data: str = ""
    error: str = ""
    fetched_at: str = field(default_factory=_utc_now_iso)

    @property
    def ok(self) -> bool:
        return self.status == OK


def ok(tool: str, data: str) -> ToolResult:
    return ToolResult(tool=tool, status=OK, data=data)


def failed(tool: str, error: str) -> ToolResult:
    return ToolResult(tool=tool, status=FAILED, error=error)


def unavailable(tool: str, error: str) -> ToolResult:
    return ToolResult(tool=tool, status=UNAVAILABLE, error=error)


def _own_failure_lead(tool: str) -> re.Pattern[str]:
    """How an unmigrated tool opens a string that says it got no answer.

    The tool name with underscores read as spaces or kept, an optional word
    "tool", then "failed" or "not configured": "prom query failed: ...",
    "gh_issue_list failed", "db_query tool not configured (...)".
    """
    spoken = re.escape(tool).replace("_", "[_ ]")
    return re.compile(rf"^{spoken}(?: tool)? (failed|not configured)\b", re.IGNORECASE)


def coerce(tool: str, value: "ToolResult | str") -> ToolResult:
    """Accept either shape, so unmigrated tools keep working unchanged.

    A plain string is OK unless it opens with the tool naming its own failure,
    which is typed as what it is (see the module docstring).
    """
    if isinstance(value, ToolResult):
        return value
    text = str(value)
    lead = _own_failure_lead(tool).match(text.lstrip())
    if lead is None:
        return ok(tool, text)
    if lead.group(1).lower() == "not configured":
        return unavailable(tool, text.strip())
    return failed(tool, text.strip())


def render(result: ToolResult) -> str:
    """The text handed to the model.

    The status line comes first and names the tool and the time, so a result
    read later in a long transcript still says when it was taken. An OK result
    keeps its payload verbatim underneath, so nothing a tool already formats is
    disturbed.
    """
    if result.status == UNAVAILABLE:
        return (
            f"UNAVAILABLE [{result.tool} @ {result.fetched_at}]: {result.error}\n"
            "This is NOT an empty result and NOT a failure of the thing you "
            "asked about: you have no way to see that data right now. Say so "
            "plainly and name what is missing."
        )
    if result.status == FAILED:
        return (
            f"FAILED [{result.tool} @ {result.fetched_at}]: {result.error}\n"
            "The tool ran and errored. This is not evidence about the thing "
            "you asked about; do not treat it as an empty result."
        )
    if not result.data.strip():
        return (
            f"OK [{result.tool} @ {result.fetched_at}]: the query matched "
            "nothing. That is not a statement about health or existence: it "
            "does not say a service is fine, a check passed or a thing is gone."
        )
    return f"OK [{result.tool} @ {result.fetched_at}]\n{result.data}"
