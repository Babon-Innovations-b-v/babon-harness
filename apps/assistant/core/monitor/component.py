"""The `Component` registry entry + the `CheckResult` a check returns.

Two flat dataclasses that ride with the monitor's public surface
(signature types live with their callable's
package, here the `registry` + `checks` seams). `Component` is one row of
the declarative registry; `CheckResult` is the classification a single
check produces.

A check classifies into one of three outcomes, NOT a bool, because
"can't tell" is a real third state the monitor must not fake green or
fake red over:

    up       the component answered and is healthy
    down     the component answered unhealthy, or is unreachable when it
             should be reachable, or a heartbeat is overdue
    unknown  the check couldn't run authoritatively (creds absent, the
             check kind isn't wireable yet), never the cause of a page

FAILURE POLICY: dataclasses only, nothing to fail. The sweep maps a
`CheckResult.classification` to the `component_status` row and decides
paging; a check that *raises* is caught by the sweep and turned into a
`down`/`unknown` `CheckResult` there (never crashes the sweep).
"""
from __future__ import annotations

from dataclasses import dataclass

# Check kinds. Each maps to one module under `checks/`.
KIND_HTTP = "http"
KIND_DB = "db"
KIND_KUBECTL = "kubectl"
KIND_HEARTBEAT = "heartbeat"
KIND_EXTERNAL = "external"

KINDS = frozenset(
    {
        KIND_HTTP,
        KIND_DB,
        KIND_KUBECTL,
        KIND_HEARTBEAT,
        KIND_EXTERNAL,
    }
)

# Classification vocabulary a check returns (mirrors the persisted status
# vocabulary in `state.component_status`, minus `pending`).
UP = "up"
DOWN = "down"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Component:
    """One declarative stack component the monitor sweeps.

    name             stable identifier (the `component_status` PK + the
                     `/webhook/heartbeat` `component` field).
    group            grouping for the chat answer (public/vm/cluster/
                     data/external).
    kind             one of `KINDS`, selects the check module.
    target           kind-specific target: a URL (http/external), an env
                     var name holding a DSN (db), a 'namespace/name'
                     deployment ref (kubectl), a container name
                     or '' (heartbeat, push-only).
    max_staleness_s  for heartbeat: how old `last_ok_at` may be before
                     the component counts as down. Ignored by active
                     checks (they re-probe every sweep).
    page_on_down     whether a down-transition pages the owner. Best-effort
                     externals set this False (an external blip is not a
                     stack outage).
    """

    name: str
    group: str
    kind: str
    target: str
    max_staleness_s: int
    page_on_down: bool


@dataclass(frozen=True)
class CheckResult:
    """The outcome of running one component's check this sweep.

    classification  one of UP / DOWN / UNKNOWN.
    detail          short human string (status code, error, 'ready', the
                    'not configured' reason) stored on the status row.
    """

    classification: str
    detail: str
