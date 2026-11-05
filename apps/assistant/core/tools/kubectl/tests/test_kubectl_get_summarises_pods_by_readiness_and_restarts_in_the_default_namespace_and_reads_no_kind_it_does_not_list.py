"""kubectl get summarises pods by readiness and restarts, in the default namespace, and reads no kind it does not list.

WHAT IT PINS. The kubectl tool group's list view, `kubectl_get.execute`, and the
namespace rule in `k8s.default_namespace`: a pod list is one line per pod with
its phase, `ready` only when every container is ready, and the restarts summed
over its containers; a call naming no namespace reads `ASSISTANT_NAMESPACE`,
or `default` when that is unset; and a kind outside the tool's list (a Secret,
above all) is answered in words without a read. The cluster is a made-up client
that records which namespace it was asked about.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Two made-up
pods: one with two containers, one not ready, restarted 1 and 2 times, so not
ready with 3 restarts; one with a single ready container that never restarted.
The text is the summary written out by hand.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row calls a pod
ready when any container is, so the half-ready pod reads ready.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from kubernetes import client as kubernetes_client

get_module = importlib.import_module("apps.assistant.core.tools.kubectl.kubectl_get")

PODS = "{'items': [{'name': 'web-1', 'phase': 'Running', 'ready': False, 'restarts': 3}, " \
       "{'name': 'worker-1', 'phase': 'Running', 'ready': True, 'restarts': 0}]}"


def _container(ready: bool, restarts: int) -> SimpleNamespace:
    return SimpleNamespace(ready=ready, restart_count=restarts)


def _pod(name: str, *containers: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name),
                           status=SimpleNamespace(phase="Running", container_statuses=list(containers)))


class _Core:
    def __init__(self, asked: list) -> None:
        self.asked = asked

    def list_namespaced_pod(self, namespace: str) -> SimpleNamespace:
        self.asked.append(namespace)
        return SimpleNamespace(items=[
            _pod("web-1", _container(True, 1), _container(False, 2)),
            _pod("worker-1", _container(True, 0)),
        ])


CASES = [
    pytest.param({"kind": "pod", "namespace": "web"}, "", (PODS, ["web"]), id="pods-summarised"),
    pytest.param({"kind": "pod"}, "assistant", (PODS, ["assistant"]), id="the-assistants-namespace-by-default"),
    pytest.param({"kind": "pod"}, "", (PODS, ["default"]), id="default-when-nothing-is-set"),
    pytest.param({"kind": "secret"}, "", ("unsupported kind: secret", []), id="a-secret-is-never-read"),
]


@pytest.mark.parametrize("tool_input, namespace_env, expected", CASES)
def test_kubectl_get_summarises_pods_by_readiness_and_restarts_in_the_default_namespace_and_reads_no_kind_it_does_not_list(
        tool_input: dict, namespace_env: str, expected: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """(the text the model reads, namespaces asked about) is the hand-written pair."""
    asked: list[str] = []
    monkeypatch.setattr(get_module, "load_config_once", lambda: None)
    monkeypatch.setattr(kubernetes_client, "CoreV1Api", lambda: _Core(asked))
    monkeypatch.setattr(kubernetes_client, "AppsV1Api", lambda: None)
    monkeypatch.setattr(kubernetes_client, "BatchV1Api", lambda: None)
    monkeypatch.setenv("ASSISTANT_NAMESPACE", namespace_env)
    assert (get_module.execute(tool_input), asked) == expected
