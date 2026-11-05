"""A GPU worker runs as uid 1000 with every capability dropped, and its volumes are writable by its group.

WHAT IT PINS. `gpu_jobs.security`: the container context
(`worker_security_context`) and the pod context (`worker_pod_security_context`)
every notulen GPU pod carries, read as the plain dict the API server receives.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
hardening the module promises in words: no privilege escalation, not
privileged, non-root as uid 1000, every Linux capability dropped, and a pod
fsGroup of 1000 so the emptyDir volumes belong to the worker's group. Each
field below is written from that sentence, not read back from the objects.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops
dropping the capabilities, so the capabilities case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from gpu_jobs.security.worker_pod_security_context import worker_pod_security_context
from gpu_jobs.security.worker_security_context import worker_security_context

CASES = [
    pytest.param("container", "allow_privilege_escalation", False, id="no-escalation"),
    pytest.param("container", "privileged", False, id="not-privileged"),
    pytest.param("container", "run_as_non_root", True, id="non-root"),
    pytest.param("container", "run_as_user", 1000, id="uid-1000"),
    pytest.param("container", "capabilities", {"add": None, "drop": ["ALL"]}, id="every-capability-dropped"),
    pytest.param("container", "read_only_root_filesystem", None, id="root-stays-writable-for-model-caches"),
    pytest.param("pod", "fs_group", 1000, id="volumes-owned-by-the-worker-group"),
]


@pytest.mark.parametrize("level, field, expected", CASES)
def test_a_gpu_worker_runs_as_uid_1000_with_every_capability_dropped_and_its_volumes_writable_by_its_group(
        level: str, field: str, expected: object) -> None:
    """The field the API server would receive is the one the hardening sentence names."""
    context = worker_security_context() if level == "container" else worker_pod_security_context()
    assert context.to_dict()[field] == expected
