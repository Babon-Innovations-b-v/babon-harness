"""The one metered agent-loop every the assistant loop runs, the deep module
behind the ten LLM callers (from the architecture review).

Before this, chat / triage / patrol / advise / digest / security_judge and
the single-shot morning / evening / compact / notify_flush each hand-copied
the same skeleton: budget precheck, `create_message`, `budget.charge`, scan
for tool_use, dispatch, iterate to a cap, catch `anthropic.APIError`. The
control flow that IS the assistant's mind lived in no module and drifted (a forgotten
`charge` overspends the daily cap). This owns it once.

`run(...) -> LoopOutcome`. The brain owns only the MECHANISM: metering,
iteration, tool dispatch, the APIError degrade. It never decides the fallback
,  it returns a plain outcome (`finished` with the terminal Message |
`budget-tripped` | `faulted` | `cap-hit`) and each caller maps that to its OWN
degrade (triage -> page-raw, patrol -> None, morning -> raw line, chat ->
error reply), where the per-loop knowledge belongs.

Two shapes fold through one loop:
- tool-loop: iterate; the model calls read/write tools (run via the caller's
  `dispatch`) until it either calls a `terminal_tool` (triage's submit) or
  returns plain text with no tool_use.
- single-shot: cap 1, empty tools, no terminal tool, one metered call, the
  text comes back inside `finished`.

The two per-loop divergences are hooks, not forks:
- `terminal_tools`: a tool whose call ends the loop (triage submit); empty for
  the text-ending loops.
- `on_text(response) -> str | None`: runs when the model returns text with no
  tool_use. Return a nudge string to append as a user turn and CONTINUE the
  loop (chat/patrol's fabrication/claims re-prompt), or None to stop. Absent ->
  always stop. The caller extracts the final answer from the returned Message.

FAILURE POLICY: Tier-2 mechanism. `run()` never raises on an Anthropic fault:
it returns `faulted` and lets the caller degrade. Budget reads/charges are
Tier-1 and propagate (a broken counter must not let spend run free). The
metered call is: is_tripped short-circuit -> create_message -> charge(
cost_usd(usage)) -> repeat.

Every run also leaves ONE metering line at INFO, prefixed `openclaw_meter`, so
what a message cost and how long it took can be grepped out of the container log and
summed: tokens (plain, cache write, cache read), USD, elapsed seconds, calls
and tool rounds. Deliberately a log line and not a table: no schema, no
dependency, and it survives the container being replaced. Every `return` below is
preceded by `meter.log(status)`; an exit path that forgets it is a hole in the
measurement.

Single public callable: `run()`. `LoopOutcome` rides with it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

from apps.assistant.shared import anthropic_cost, budget

if TYPE_CHECKING:
    import anthropic

log = logging.getLogger("openclaw.brain")

LoopStatus = Literal["finished", "budget-tripped", "faulted", "cap-hit"]


@dataclass(frozen=True)
class LoopOutcome:
    """What one `run()` produced. `finished` carries the terminal Anthropic
    Message (the caller extracts its answer / submit payload / note); the other
    three are degrade signals the caller maps to its own fallback."""

    status: LoopStatus
    response: anthropic.types.Message | None = None

    @property
    def finished(self) -> bool:
        return self.status == "finished"


@dataclass
class _Meter:
    """What one `run()` spent: tokens, USD, tool rounds, wall clock.

    Cheap on purpose. A handful of counters in memory and one log line when the
    run ends; the container log is the store, so there is nothing to migrate and
    nothing to keep alive.
    """

    started: float = field(default_factory=time.monotonic)
    calls: int = 0
    tool_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0

    def record_call(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int,
        cache_read_input_tokens: int,
        cost_usd: float,
    ) -> None:
        """Add one Anthropic call's usage to the tally."""
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        self.cost_usd += cost_usd

    def log(self, status: LoopStatus) -> None:
        """Emit this run's one metering line, greppable as `openclaw_meter`."""
        log.info(
            "openclaw_meter status=%s calls=%d tool_rounds=%d input_tokens=%d "
            "output_tokens=%d cache_creation_input_tokens=%d "
            "cache_read_input_tokens=%d cost_usd=%.6f elapsed_s=%.3f",
            status,
            self.calls,
            self.tool_rounds,
            self.input_tokens,
            self.output_tokens,
            self.cache_creation_input_tokens,
            self.cache_read_input_tokens,
            self.cost_usd,
            time.monotonic() - self.started,
        )


def _tool_use_blocks(response: anthropic.types.Message) -> list:
    return [block for block in response.content if getattr(block, "type", None) == "tool_use"]


def _noop_dispatch(_name: str, _tool_input: dict) -> str:
    return ""


def run(
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    cap: int,
    dispatch: Callable[[str, dict], str] = _noop_dispatch,
    terminal_tools: frozenset[str] = frozenset(),
    on_text: Callable[[anthropic.types.Message], str | None] | None = None,
    recheck_budget: bool = False,
) -> LoopOutcome:
    """Run the bounded, budget-metered Anthropic loop.

    `messages` is mutated in place (the loop appends assistant + tool_result
    turns), so pass the caller's own seed list. `dispatch(name, input) -> str`
    runs one tool and returns its result text; the default no-op is for
    single-shot (empty `tools`) calls. `terminal_tools` names tools whose
    appearance ends the loop with `finished`. `on_text` runs when the model
    returns text with no tool_use: a returned string is appended as a user
    nudge and the loop continues; None stops with `finished`. `recheck_budget`
    re-checks the cap after each tool round (patrol/advise/security skip a pass
    on a mid-loop trip); the pre-check always runs. Whichever way the run ends,
    it logs one `openclaw_meter` line first.
    """
    # The SDK is imported here, not at module level: this module sits behind the
    # `core` seam that pure-CalDAV leaves import without anthropic installed.
    import anthropic

    from apps.assistant.shared import anthropic_client

    meter = _Meter()

    if budget.is_tripped():
        meter.log("budget-tripped")
        return LoopOutcome("budget-tripped")

    for _iteration in range(cap):
        try:
            response = anthropic_client.create_message(
                system=system, messages=messages, tools=tools
            )
        except anthropic.APIError as exc:
            # Tier-2: an Anthropic outage returns `faulted`; the caller degrades.
            log.warning("anthropic call failed: %s", exc)
            meter.log("faulted")
            return LoopOutcome("faulted")

        usage = response.usage
        # Cache counters are present only when prompt caching is active; default 0.
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        call_cost_usd = anthropic_cost.cost_usd(
            usage.input_tokens,
            usage.output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
        )
        budget.charge(call_cost_usd)
        meter.record_call(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
            cost_usd=call_cost_usd,
        )

        blocks = _tool_use_blocks(response)
        if terminal_tools and any(block.name in terminal_tools for block in blocks):
            meter.log("finished")
            return LoopOutcome("finished", response)

        tool_results = []
        for block in blocks:
            result_text = dispatch(block.name, dict(block.input))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }
            )

        if not tool_results:
            nudge = on_text(response) if on_text else None
            if nudge is None:
                meter.log("finished")
                return LoopOutcome("finished", response)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": nudge})
            continue

        meter.tool_rounds += 1
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        if recheck_budget and budget.is_tripped():
            meter.log("budget-tripped")
            return LoopOutcome("budget-tripped")

    meter.log("cap-hit")
    return LoopOutcome("cap-hit")
