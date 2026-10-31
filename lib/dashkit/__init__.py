"""dashkit: the shared library behind the harness dashboards.

**Library, not application.** Dashboards import it; it never imports a
dashboard. Worker images leave it out on purpose, so ``import dashkit``
from worker code raises ModuleNotFoundError, and that import boundary
is the contract.

Layout (each subpackage carries its own module map):

- ``core``     bootstrap and observability primitives: app_factory,
               auth, db, constants, inspector, audit/, sync/.
- ``ai``       the single LLM metering seam (``call_claude``).
- ``frontend`` static JS/CSS assets served at ``/static/dashkit/*``.

dashkit has no entrypoint and no gates: it is a consumed library, a
deliberate exception to the layered shape the applications follow.

FAILURE POLICY: observability writes (activity log, AI-call accounting)
are best-effort and fail open. Each subpackage seam declares its own
split.
"""

from __future__ import annotations

from dashkit import ai  # noqa: F401
from dashkit.core import (  # noqa: F401
    app_factory,
    audit,
    auth,
    constants,
    db,
    inspector,
    sync,
)
from dashkit.core.app_factory import (
    DashkitConfig,
    make_dashboard_app,
)

__all__ = [
    "DashkitConfig",
    "ai",
    "app_factory",
    "audit",
    "auth",
    "constants",
    "db",
    "inspector",
    "make_dashboard_app",
    "sync",
]
