"""A notulen Job carries the name the naming grammar gives, the hardened contexts, and the cluster's namespace.

WHAT IT PINS. How the modules of `gpu_jobs` fit: `creators` builds the Job,
but its name comes from `naming`, its container and pod contexts from
`security`, and the namespace it is posted to from `cluster`. The seam is the
package's public `create_notulen_job`, with the cluster's create call replaced
by a recorder, so nothing leaves the box.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The job id is
made up here, and the name is cut from it by hand: `notulen-` and the first 20
characters of the id. The two contexts are written out below as the posture the
package documents (no privilege escalation, every capability dropped, uid 1000,
fs group 1000), and the namespace is the value this test puts in
`GPU_NAMESPACE`. None of the three is read from the code under test.

ONE FUNCTION. This group's one test. A new check is a parametrized case of it,
never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops the
container dropping its capabilities, so the container-context case fails.

GUARDS. One test per module group (#1210), 2026-11-04.
"""
from __future__ import annotations

import base64
from typing import Any

import pytest
from kubernetes import client

from gpu_jobs import create_notulen_job
from gpu_jobs.cluster import ensure_config as ensure_config_module

JOB_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
NAMESPACE = "meetings-example"

#: A cluster nobody can reach: the config loads, every real call would fail.
_DEAD_KUBECONFIG = """apiVersion: v1
kind: Config
clusters:
- name: nowhere
  cluster:
    server: https://127.0.0.1:1
    insecure-skip-tls-verify: true
contexts:
- name: nowhere
  context: {cluster: nowhere, user: nowhere}
current-context: nowhere
users:
- name: nowhere
  user: {token: not-a-real-token}
"""

CASES = [
    pytest.param(("metadata", "name"), "notulen-0a1b2c3d-4e5f-4a6b-8", id="named-by-the-grammar"),
    pytest.param(("metadata", "namespace"), NAMESPACE, id="in-the-cluster-namespace"),
    pytest.param(
        ("spec", "template", "spec", "containers", 0, "securityContext"),
        {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
         "privileged": False, "runAsNonRoot": True, "runAsUser": 1000},
        id="container-hardened",
    ),
    pytest.param(("spec", "template", "spec", "securityContext"), {"fsGroup": 1000}, id="pod-hardened"),
]


def _posted(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], str | None]:
    """The Job the package posts for JOB_ID, as the API would receive it, and where it was posted."""
    posted: dict[str, Any] = {}

    def recorder(self, namespace=None, body=None, **kwargs):
        posted["job"], posted["namespace"] = body, namespace
        return body

    monkeypatch.setattr(client.BatchV1Api, "create_namespaced_job", recorder)
    monkeypatch.setenv("KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode())
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/team/notulen-worker:v1")
    monkeypatch.setenv("GPU_NAMESPACE", NAMESPACE)
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job(JOB_ID, "notulen/audio/call.webm", "Call", "2026-01-15",
                           count_recent_jobs=lambda: 0)
        return client.ApiClient().sanitize_for_serialization(posted["job"]), posted["namespace"]
    finally:
        client.Configuration.set_default(previous_default)


@pytest.mark.parametrize("path, expected", CASES)
def test_a_notulen_job_carries_the_name_the_naming_grammar_the_hardened_contexts_and_the_cluster_namespace(
        path: tuple, expected: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The posted Job holds the hand-derived value at this path, and it went to the namespace it names."""
    job, posted_to = _posted(monkeypatch)
    found: Any = job
    for step in path:
        found = found[step]
    assert found == expected
    assert posted_to == job["metadata"]["namespace"]
