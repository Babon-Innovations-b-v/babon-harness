"""A Deployment scaled to zero on purpose is parked, not down.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

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

import inspect
import pytest


# From a deployment scaled to zero on purpose is parked not down.

from types import SimpleNamespace


from kubernetes import client as k8s_client


from apps.assistant.core.monitor.checks import kubectl


from apps.assistant.core.monitor.component import DOWN, KIND_KUBECTL, UP, Component


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


def _a_deployment_scaled_to_zero_on_purpose_is_parked_not_down(monkeypatch) -> None:
    """Desired 0, ready None (what the API returns then): up, reported parked."""
    _cluster_answers(monkeypatch, desired=0, ready=None)

    assert kubectl.check(_SERVE).classification == UP


def _a_deployment_that_wants_a_pod_and_has_none_is_down(monkeypatch) -> None:
    """Desired 1, nothing ready: still down."""
    _cluster_answers(monkeypatch, desired=1, ready=None)

    assert kubectl.check(_SERVE).classification == DOWN


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_deployment_scaled_to_zero_on_purpose_is_parked_not_down),
    *_cases(_a_deployment_that_wants_a_pod_and_has_none_is_down),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_deployment_scaled_to_zero_on_purpose_is_parked_not_down(scenario, given, uses, request):
    """A Deployment scaled to zero on purpose is parked, not down: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
