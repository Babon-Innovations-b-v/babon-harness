"""Stack-liveness monitor, the package seam.

openclaw owns a declarative registry of every stack component that
nothing else in the stack can see, sweeps them on a short interval,
records each component's status in SQLite (`state.component_status`),
and, the moment one flips down, puts it in the notify pen as a ping.
The pen is the only road to the phone: it owns muting, dedup, the story
gap and the shape of the page, and this package has no send path of its
own (`sweep.py`, and the test named for it). The registry also answers
"is everything alive?" authoritatively via the `stack_status` chat tool.

Modules:

    component.py   `Component` registry entry + `CheckResult` (the
                   up/down/unknown classification).
    registry.py    `REGISTRY`, the declarative list of components.
    checks/        one module per check kind (http/db/kubectl/
                   heartbeat/external); `run_check`
                   dispatches by kind.
    sweep.py       `run_sweep()`, pure pass over the registry returning
                   the transitions; queues the down ones in the notify
                   pen once the digest has judged them.
    digest.py      `digest_transitions(transitions)`, the LLM brain that
                   judges a sweep's down components real-vs-noise, and in
                   particular tells a deploy restart from an outage.
                   None means SILENT; anything else means say it.
    runner.py      `start_runner()`, the in-container daemon thread driving
                   the sweep on an interval (NOT a CronJob: one volume).
    limits.py      sweep interval, down-threshold, check timeout.

FAILURE POLICY (two-tier, see module docstrings): the `component_status`
writes are Tier-1 loud (the monitor must not lie); the check transport
failures and the reporting are Tier-2 (a check fault classifies down/
unknown, a digest or pen failure is swallowed + logged, so the sweep never
crashes and never blocks /health).
"""
from __future__ import annotations

from apps.assistant.core.monitor.component import (
    Component,
    CheckResult,
)
from apps.assistant.core.monitor.digest import digest_transitions
from apps.assistant.core.monitor.registry import REGISTRY
from apps.assistant.core.monitor.runner import start_runner, stop_runner
from apps.assistant.core.monitor.sweep import Transition, run_sweep

__all__ = [
    "REGISTRY",
    "CheckResult",
    "Component",
    "Transition",
    "digest_transitions",
    "run_sweep",
    "start_runner",
    "stop_runner",
]
