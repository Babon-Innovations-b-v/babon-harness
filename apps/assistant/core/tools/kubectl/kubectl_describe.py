"""Read-only `kubectl_describe` tool, full single-resource detail
(events, conditions, container statuses), backed by the Python
kubernetes client.

Mirrors `kubectl_get`'s client use + `load_config_once`, but reads ONE
named resource and returns its full `to_dict()` so the LLM sees the
reason a pod is stuck / a node is NotReady. Output is truncated by
`text.truncate`. Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: errors propagate to the registry's defended Tier-2
catch (`core.tools.execute`), which feeds them back to the LLM as
text.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.tools.kubectl import k8s
from apps.assistant.core.tools.kubectl.k8s import load_config_once
from apps.assistant.core.tools.meta.text import truncate

NAME = "kubectl_describe"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "kubectl describe of one named pod, deployment, node or cronjob: "
        "conditions, container statuses, why it is stuck. Cannot read Secrets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Ignored for node.",
            },
            "kind": {
                "type": "string",
                "description": "Resource kind.",
                "enum": ["pod", "deployment", "node", "cronjob"],
            },
            "name": {
                "type": "string",
                "description": "Resource name.",
            },
        },
        "required": ["kind", "name"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    # Lazy cluster dep (module standard §3): see `k8s.load_config_once`.
    from kubernetes import client as _k8s_client  # noqa: PLC0415

    load_config_once()
    kind = tool_input["kind"]
    name = tool_input["name"]
    namespace = tool_input.get("namespace") or k8s.default_namespace()
    core = _k8s_client.CoreV1Api()
    apps = _k8s_client.AppsV1Api()
    batch = _k8s_client.BatchV1Api()

    if kind == "pod":
        payload = core.read_namespaced_pod(name=name, namespace=namespace).to_dict()
    elif kind == "deployment":
        payload = apps.read_namespaced_deployment(name=name, namespace=namespace).to_dict()
    elif kind == "node":
        payload = core.read_node(name=name).to_dict()
    elif kind == "cronjob":
        payload = batch.read_namespaced_cron_job(name=name, namespace=namespace).to_dict()
    else:
        return f"unsupported kind: {kind}"

    return truncate(str(payload))
