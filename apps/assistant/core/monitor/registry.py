"""The stack-component registry: the declarative source of truth for "the
stack" the assistant sweeps.

`REGISTRY` is the list the sweep walks. Each entry is a `Component` (see
`component.py`): name, group, check kind, target, max-staleness,
page-on-down. The sweep and the `stack_status` chat tool both read this
list, so it is the only place "what counts as the stack" is written down.

Groups:

    public    user-facing surfaces: http GET, 2xx/3xx = up. Page-worthy.
    vm        services on the server that prove themselves by POSTing
              /webhook/heartbeat (push), such as the Signal send canary.
    cluster   Kubernetes Deployments, kubectl readiness. Only present when
              a kubeconfig is wired and MONITOR_DEPLOYMENTS names some.
    data      Postgres, `SELECT 1` on a read-only DSN env var.
    external  third-party APIs, best-effort, never the cause of a page.

THE RULE FOR AN ENTRY. It earns its place only where nothing else in the
stack can see the failure it names. A surface Prometheus already probes with
a page-worthy rule does not belong here too: two clocks on one fact page
twice and disagree about when.

Configuration, all optional, read when this module is imported:

    MONITOR_HTTP_TARGETS   comma-separated `name=https://url` public probes
    MONITOR_DEPLOYMENTS    comma-separated `namespace/deployment` readiness
    OPENCLAW_DB_RO_URL     the read-only DSN the data check uses

WIREABILITY HONESTY: a check whose credentials are absent classifies
`unknown`, never green and never down, and `unknown` never counts toward the
down threshold, so an unwired check cannot page whatever its page_on_down
says.

FAILURE POLICY: data only, nothing to fail. A malformed env entry is skipped.
"""
from __future__ import annotations

import os

from apps.assistant.core.monitor.component import (
    KIND_DB,
    KIND_EXTERNAL,
    KIND_HEARTBEAT,
    KIND_HTTP,
    KIND_KUBECTL,
    Component,
)


def _http_targets() -> tuple[Component, ...]:
    found: list[Component] = []
    for entry in os.environ.get("MONITOR_HTTP_TARGETS", "").split(","):
        name, separator, url = entry.strip().partition("=")
        if separator and name.strip() and url.strip().startswith("http"):
            found.append(Component(name.strip(), "public", KIND_HTTP, url.strip(), 0, True))
    return tuple(found)


def _deployments() -> tuple[Component, ...]:
    found: list[Component] = []
    for entry in os.environ.get("MONITOR_DEPLOYMENTS", "").split(","):
        target = entry.strip()
        if target.count("/") == 1 and all(target.split("/")):
            found.append(Component(target.split("/")[1], "cluster", KIND_KUBECTL, target, 0, True))
    return tuple(found)


REGISTRY: tuple[Component, ...] = (
    *_http_targets(),
    # The SEND path, watched separately from the signal-cli container. A
    # container that is up proves it answers, not that a message was accepted;
    # the send canary beats only when one was. Its cadence is half an hour, so
    # this window is about twice that plus margin.
    Component("signal-send", "vm", KIND_HEARTBEAT, "", 4200, True),
    *_deployments(),
    Component("ops-postgres", "data", KIND_DB, "OPENCLAW_DB_RO_URL", 0, True),
    # page_on_down=False, so these can never put anything on a phone. They
    # answer one question a person asks the chat: "is it us or is it them".
    Component("anthropic", "external", KIND_EXTERNAL, "https://api.anthropic.com/v1/models", 0, False),
    Component("github", "external", KIND_EXTERNAL, "https://api.github.com/rate_limit", 0, False),
)
