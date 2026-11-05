"""The gpu pool role carries the taint the notulen jobs tolerate, and its pool names are where a notulen pod may land.

WHAT IT PINS. How two infra modules fit: `infra.cluster.pool_fallbacks` makes
the gpu role's pools from `POOL_GPU_*`, and `gpu_jobs.config` says which pools
a notulen pod may land on (`GPU_POOL`) and which taint it tolerates. A pool
whose taint the pod does not tolerate, or a pod pointed at pools the cluster
never made, leaves every meeting waiting on a GPU that cannot take it.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The settings
are the shipped `config/harness.env.example` read as plain `KEY=value` lines;
its gpu taint line says `workload=notulen`, and the pod's toleration must be
that pair. The made-up role with two types and two zones is ordered by hand
from the documented rule: preferred type in the home zone first, named after
the role, then the other type at home, then the other zone.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row changes the
taint value the notulen pods tolerate, so the shipped-taint case fails.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gpu_jobs.config.notulen_pool import NOTULEN_POOL_TAINT_KEY, NOTULEN_POOL_TAINT_VALUE, notulen_pool_names
from infra.cluster.pool_fallbacks import pools

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "harness.env.example"

TWO_BY_TWO = {
    "POOL_ROLES": "gpu",
    "POOL_ROLE_LABEL": "harness/role",
    "CLUSTER_ZONES": "fr-par-2,fr-par-1",
    "POOL_GPU_TYPES": "L4-1-24G,L40S-1-48G",
    "POOL_GPU_MIN": "0",
    "POOL_GPU_MAX": "1",
    "POOL_GPU_DISK": "125GB",
    "POOL_GPU_TAINT": "workload=notulen",
}


def _shipped() -> dict[str, str]:
    """The example settings, one `KEY=value` per line, comments and blanks skipped."""
    settings: dict[str, str] = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        key, equals, value = line.partition("=")
        if equals and not line.lstrip().startswith("#"):
            settings[key.strip()] = value.strip()
    return settings


def _gpu_taints(settings: dict[str, str]) -> set:
    return {spec.taints for spec in pools(settings) if spec.role == "gpu"}


def _pod_lands_where_the_pools_are(settings: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> tuple:
    names = tuple(spec.name for spec in pools(settings) if spec.role == "gpu")
    monkeypatch.setenv("GPU_POOL", ",".join(names))
    return notulen_pool_names()


CASES = [
    pytest.param(
        lambda monkeypatch: _gpu_taints(_shipped()),
        {((NOTULEN_POOL_TAINT_KEY, NOTULEN_POOL_TAINT_VALUE, "NoSchedule"),)},
        id="the-shipped-gpu-taint-is-the-one-the-pods-tolerate",
    ),
    pytest.param(
        lambda monkeypatch: (NOTULEN_POOL_TAINT_KEY, NOTULEN_POOL_TAINT_VALUE),
        ("workload", "notulen"),
        id="the-toleration-is-the-example-lines-pair",
    ),
    pytest.param(
        lambda monkeypatch: _pod_lands_where_the_pools_are(TWO_BY_TWO, monkeypatch),
        ("gpu", "gpu-l40s-1-48g-fr-par-2", "gpu-l4-1-24g-fr-par-1", "gpu-l40s-1-48g-fr-par-1"),
        id="the-pod-takes-the-pools-preferred-first",
    ),
]


@pytest.mark.parametrize("ask, expected", CASES)
def test_the_gpu_pool_role_carries_the_taint_the_notulen_jobs_tolerate_and_its_pool_names_are_where_a_notulen_pod_may_land(
        ask, expected, monkeypatch: pytest.MonkeyPatch) -> None:
    """What the two modules say together is the hand-derived answer."""
    assert ask(monkeypatch) == expected
