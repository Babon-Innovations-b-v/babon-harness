"""A cluster call stale on its token reloads the config and retries once, and any other refusal propagates.

WHAT IT PINS. `gpu_jobs.cluster`, through its one door `cluster()`: the handle's
`call` (the one-retry-on-401 wrapper the creators use) and its `namespace`,
read from the environment at the moment `cluster()` is called. The kubeconfig
bootstrap is replaced by a recorder, so nothing reaches a cluster.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
made-up API function that answers a scripted sequence (a 401 then a result, a
403, two 401s), and the expected outcome is written from the rule: exactly one
forced reload and one retry after a 401, nothing retried for any other status.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops
recognising 401, so the stale-token case raises instead of retrying.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib

import pytest
from kubernetes import client

ensure_module = importlib.import_module("gpu_jobs.cluster.ensure_config")
call_module = importlib.import_module("gpu_jobs.cluster.k8s_call")
cluster_module = importlib.import_module("gpu_jobs.cluster.cluster")

CASES = [
    pytest.param((401, "jobs"), "", ("jobs", 1, 2, "notulen"), id="a-stale-token-is-reloaded-and-retried-once"),
    pytest.param(("jobs",), "gpu-batch", ("jobs", 0, 1, "gpu-batch"), id="a-good-call-is-made-once"),
    pytest.param((403,), "", (403, 0, 1, "notulen"), id="a-forbidden-call-is-not-retried"),
    pytest.param((401, 401), "", (401, 1, 2, "notulen"), id="a-second-401-propagates"),
]


@pytest.mark.parametrize("answers, namespace_env, expected", CASES)
def test_a_cluster_call_stale_on_its_token_reloads_the_config_and_retries_once_and_any_other_refusal_propagates(
        answers: tuple, namespace_env: str, expected: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """(result or status raised, forced reloads, calls made, namespace) is the scripted one."""
    reloads: list[bool] = []
    monkeypatch.setattr(cluster_module, "ensure_config", lambda **kwargs: None)
    monkeypatch.setattr(call_module, "ensure_config", lambda **kwargs: reloads.append(kwargs.get("force", False)))
    if namespace_env:
        monkeypatch.setenv("GPU_NAMESPACE", namespace_env)
    else:
        monkeypatch.delenv("GPU_NAMESPACE", raising=False)
    script = list(answers)
    calls: list[int] = []

    def api_function() -> str:
        calls.append(1)
        answer = script.pop(0)
        if isinstance(answer, int):
            raise client.ApiException(status=answer)
        return answer

    handle = cluster_module.cluster()
    try:
        outcome: object = handle.call(api_function)
    except client.ApiException as refusal:
        outcome = refusal.status
    assert (outcome, len([forced for forced in reloads if forced]), len(calls), handle.namespace) == expected
