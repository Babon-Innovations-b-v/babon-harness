"""Read-only `kubectl_get` tool, single-resource-kind state view,
backed by the Python kubernetes client.

We return text (the LLM consumes text), not structured data. Output is
truncated by `text.truncate` so one noisy resource can't eat the
budget. Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: errors propagate to the registry's defended Tier-2
catch (`core.tools.execute`), which feeds them back to the LLM as
text.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.tools.kubectl import k8s
from apps.assistant.core.tools.kubectl.k8s import load_config_once
from apps.assistant.core.tools.meta.text import truncate

NAME = "kubectl_get"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": "kubectl get for one resource kind, as a short table. Cannot read Secrets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "e.g. 'default'.",
            },
            "kind": {
                "type": "string",
                "description": "Resource kind.",
                "enum": ["pod", "cronjob", "deployment", "service", "node"],
            },
            "name": {
                "type": "string",
                "description": "Optional; omit for all in the namespace.",
            },
        },
        "required": ["kind"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    # Lazy cluster dep (module standard §3): see `k8s.load_config_once`.
    from kubernetes import client as _k8s_client  # noqa: PLC0415

    load_config_once()
    namespace = tool_input.get("namespace") or k8s.default_namespace()
    kind = tool_input["kind"]
    name = tool_input.get("name")
    core = _k8s_client.CoreV1Api()
    apps = _k8s_client.AppsV1Api()
    batch = _k8s_client.BatchV1Api()

    if kind == "pod":
        if name:
            payload = core.read_namespaced_pod(name=name, namespace=namespace).to_dict()
        else:
            payload = {
                "items": [
                    {
                        "name": item.metadata.name,
                        "phase": item.status.phase,
                        "ready": all(
                            (status.ready for status in (item.status.container_statuses or []))
                        ),
                        "restarts": sum(
                            (status.restart_count for status in (item.status.container_statuses or []))
                        ),
                    }
                    for item in core.list_namespaced_pod(namespace=namespace).items
                ]
            }
    elif kind == "cronjob":
        if name:
            payload = batch.read_namespaced_cron_job(name=name, namespace=namespace).to_dict()
        else:
            payload = {
                "items": [
                    {
                        "name": item.metadata.name,
                        "schedule": item.spec.schedule,
                        "suspend": bool(item.spec.suspend),
                        "last_schedule_time": str(item.status.last_schedule_time)
                        if item.status.last_schedule_time
                        else None,
                    }
                    for item in batch.list_namespaced_cron_job(namespace=namespace).items
                ]
            }
    elif kind == "deployment":
        if name:
            payload = apps.read_namespaced_deployment(name=name, namespace=namespace).to_dict()
        else:
            payload = {
                "items": [
                    {
                        "name": item.metadata.name,
                        "ready_replicas": item.status.ready_replicas,
                        "replicas": item.spec.replicas,
                    }
                    for item in apps.list_namespaced_deployment(namespace=namespace).items
                ]
            }
    elif kind == "service":
        payload = {
            "items": [
                {"name": item.metadata.name, "type": item.spec.type}
                for item in core.list_namespaced_service(namespace=namespace).items
            ]
        }
    elif kind == "node":
        payload = {
            "items": [
                {
                    "name": item.metadata.name,
                    "conditions": [
                        {"type": cond.type, "status": cond.status}
                        for cond in (item.status.conditions or [])
                    ],
                }
                for item in core.list_node().items
            ]
        }
    else:
        return f"unsupported kind: {kind}"

    return truncate(str(payload))
