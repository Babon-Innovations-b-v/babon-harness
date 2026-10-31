"""Read-only `kubectl_events` tool, recent events in a namespace,
backed by the Python kubernetes client (`CoreV1Api.list_namespaced_event`).

Events are the fastest "what just happened" signal (OOMKilled,
FailedScheduling, BackOff). Mirrors `kubectl_get`'s client use +
`load_config_once`. Output is truncated by `text.truncate`. Tool-module
grammar: `NAME`, `DEFINITION`, `execute`.

The kubeconfig's read-only role must grant `get`/`list` on
core-API `events` (see `infra/gpu/k8s/rbac.yaml`).

FAILURE POLICY: errors propagate to the registry's defended Tier-2
catch (`core.tools.execute`), which feeds them back to the LLM as
text.
"""
from __future__ import annotations

import datetime
from typing import Any

from apps.assistant.core.tools.kubectl import k8s
from apps.assistant.core.tools.kubectl.k8s import load_config_once
from apps.assistant.core.tools.meta.text import truncate

NAME = "kubectl_events"

# Cap on returned events so one noisy namespace can't eat the budget;
# truncate() bounds bytes, this bounds count for readable ordering.
_EVENT_LIMIT = 40

# Sort floor for an event carrying neither timestamp: it goes last, never
# ahead of an event that knows when it happened.
_EPOCH = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": "Recent Kubernetes events in a namespace (OOMKilled, FailedScheduling, BackOff).",
    "input_schema": {
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Omit for the default namespace.",
            },
        },
        "required": [],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    # Lazy cluster dep (module standard §3): see `k8s.load_config_once`.
    from kubernetes import client as _k8s_client  # noqa: PLC0415

    load_config_once()
    namespace = tool_input.get("namespace") or k8s.default_namespace()
    core = _k8s_client.CoreV1Api()
    events = core.list_namespaced_event(namespace=namespace).items
    # Newest first, explicitly. The API returns items in resourceVersion
    # order, not time order, and this used to take `events[-_EVENT_LIMIT:]`,
    # the LAST slice of an unsorted list. So "recent events" could be old ones
    # while the events that just happened were dropped, which is the opposite
    # of what anybody asks this tool for.
    events = sorted(
        events,
        key=lambda item: item.last_timestamp or item.event_time or _EPOCH,
        reverse=True,
    )
    payload = {
        "items": [
            {
                "last_seen": str(item.last_timestamp) if item.last_timestamp else None,
                "type": item.type,
                "reason": item.reason,
                "object": f"{item.involved_object.kind}/{item.involved_object.name}"
                if item.involved_object
                else None,
                "message": item.message,
            }
            for item in events[:_EVENT_LIMIT]
        ]
    }
    return truncate(str(payload))
