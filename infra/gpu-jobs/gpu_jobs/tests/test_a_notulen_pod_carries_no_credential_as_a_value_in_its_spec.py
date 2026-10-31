"""A notulen GPU pod gets its credentials by reference to a cluster Secret, so
no credential is readable by someone who can only read pods.

WHAT IT PINS. `gpu_jobs.create_notulen_job`, through its public interface: the
Job manifest it posts. Only the HTTP POST is replaced by a recorder.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The dashboard
that calls it holds the credentials the worker reads (`entrypoints/worker.py`:
DB_URL, ANTHROPIC_API_KEY, HF_TOKEN, S3_ACCESS_KEY, S3_SECRET_KEY) in its own
environment. The test sets each to a sentinel string, so whatever the code
does, a sentinel showing up anywhere in the posted manifest means a credential
was copied into the pod spec. Each must still reach the container, by
`secretKeyRef` on `notulen-worker-secrets`, or the worker runs without it.

WHAT IT WAS PROVED AGAINST. The Anthropic key copied from the environment as a
value.
"""
from __future__ import annotations

import base64
import json

from kubernetes import client

from gpu_jobs import create_notulen_job
from gpu_jobs.cluster import ensure_config as ensure_config_module

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
_SENTINELS = {
    "DB_URL": "postgresql://app:sentinel-app-password@db/app",
    "DB_URL_OPS": "postgresql://ops:sentinel-ops-password@db/ops",
    "ANTHROPIC_API_KEY": "sk-ant-sentinel-anthropic",
    "HF_TOKEN": "hf_sentinel_huggingface",
    "S3_ACCESS_KEY": "SCWSENTINELACCESSKEY",
    "S3_SECRET_KEY": "sentinel-s3-secret-key",
}
# Env name in the pod -> (Secret, key) it must come from.
_EXPECTED_REFS = {
    "DB_URL": ("notulen-worker-secrets", "DB_URL"),
    "ANTHROPIC_API_KEY": ("notulen-worker-secrets", "ANTHROPIC_API_KEY"),
    "HF_TOKEN": ("notulen-worker-secrets", "HF_TOKEN"),
    "S3_ACCESS_KEY": ("notulen-worker-secrets", "S3_ACCESS_KEY"),
    "S3_SECRET_KEY": ("notulen-worker-secrets", "S3_SECRET_KEY"),
}


def test_a_notulen_pod_carries_no_credential_as_a_value_in_its_spec(monkeypatch) -> None:
    """No sentinel in the manifest; each credential arrives by secretKeyRef."""
    posted: dict = {}
    monkeypatch.setattr(
        client.BatchV1Api, "create_namespaced_job",
        lambda self, namespace=None, body=None, **kwargs: posted.setdefault("job", body),
    )
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode()
    )
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/harness/notulen-worker:v1")
    for name, sentinel in _SENTINELS.items():
        monkeypatch.setenv(name, sentinel)
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job(
            "00000000-1111-4222-8333-444444444444",
            "notulen/audio/2026-01-15-call.webm", "Call", "2026-01-15",
            count_recent_jobs=lambda: 0,
        )
        job = client.ApiClient().sanitize_for_serialization(posted["job"])
    finally:
        client.Configuration.set_default(previous_default)

    manifest = json.dumps(job)
    leaked = [name for name, sentinel in _SENTINELS.items() if sentinel in manifest]
    assert not leaked, f"credentials copied into the pod spec as values: {leaked}"

    env = {
        entry["name"]: entry
        for entry in job["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    for name, (secret, key) in _EXPECTED_REFS.items():
        ref = env.get(name, {}).get("valueFrom", {}).get("secretKeyRef", {})
        assert (ref.get("name"), ref.get("key")) == (secret, key), (
            f"{name} must come from Secret {secret!r} key {key!r}, got {env.get(name)}"
        )
