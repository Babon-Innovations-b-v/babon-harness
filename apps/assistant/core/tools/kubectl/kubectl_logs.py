"""Read-only `kubectl_logs` tool, tail a pod's stdout/stderr to
capture the traceback an alert points at.

Output is truncated by `text.truncate`. Tool-module grammar: `NAME`,
`DEFINITION`, `execute`.

FAILURE POLICY: errors propagate to the registry's defended Tier-2
catch (`core.tools.execute`), which feeds them back to the LLM as
text.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.tools.kubectl import k8s
from apps.assistant.core.tools.kubectl.k8s import load_config_once
from apps.assistant.core.tools.meta.text import truncate

NAME = "kubectl_logs"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": "The last lines of a pod's stdout/stderr log.",
    "input_schema": {
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "pod": {"type": "string"},
            "tail": {
                "type": "integer",
                "description": "Line count, max 200.",
                "default": 100,
            },
        },
        "required": ["pod"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    # Lazy cluster dep (module standard §3): see `k8s.load_config_once`.
    from kubernetes import client as _k8s_client  # noqa: PLC0415

    load_config_once()
    namespace = tool_input.get("namespace") or k8s.default_namespace()
    pod_name = tool_input["pod"]
    tail = min(int(tool_input.get("tail", 100)), 200)
    core = _k8s_client.CoreV1Api()
    logs = core.read_namespaced_pod_log(
        name=pod_name, namespace=namespace, tail_lines=tail
    )
    return truncate(logs)
