"""A Deployment scaled to zero on purpose is parked, not down.

WHAT IT PINS. `monitor.checks.kubectl.check`, the classification the assistant's
stack monitor gives a Deployment. One that asks for 0 replicas has been
scaled down deliberately (a GPU workload paused to save cost, say) and must not
count toward DOWN_THRESHOLD or re-page hourly; one that asks for 1 and has
0 ready is still down.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
Deployment object alone: desired 0 means nothing is meant to run, so
nothing is missing; desired 1 with 0 ready means the one pod that should be
serving is not.
"""
from __future__ import annotations

from types import SimpleNamespace

from kubernetes import client as k8s_client

from apps.assistant.core.monitor.checks import kubectl
from apps.assistant.core.monitor.component import (
    DOWN,
    KIND_KUBECTL,
    UP,
    Component,
)

_SERVE = Component("batch-runner", "cluster", KIND_KUBECTL, "default/batch-runner", 0, True)


def _cluster_answers(monkeypatch, desired: int, ready: int | None) -> None:
    deployment = SimpleNamespace(
        spec=SimpleNamespace(replicas=desired),
        status=SimpleNamespace(ready_replicas=ready),
    )

    class _Apps:
        def read_namespaced_deployment(self, **_kwargs):
            return deployment

    monkeypatch.setattr(kubectl, "load_config_once", lambda: None)
    monkeypatch.setattr(k8s_client, "AppsV1Api", _Apps)


def test_a_deployment_scaled_to_zero_on_purpose_is_parked_not_down(monkeypatch) -> None:
    """Desired 0, ready None (what the API returns then): up, reported parked."""
    _cluster_answers(monkeypatch, desired=0, ready=None)

    assert kubectl.check(_SERVE).classification == UP


def test_a_deployment_that_wants_a_pod_and_has_none_is_down(monkeypatch) -> None:
    """Desired 1, nothing ready: still down."""
    _cluster_answers(monkeypatch, desired=1, ready=None)

    assert kubectl.check(_SERVE).classification == DOWN
