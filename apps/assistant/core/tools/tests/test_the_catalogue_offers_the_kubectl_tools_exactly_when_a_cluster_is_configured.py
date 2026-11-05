"""The catalogue offers the kubectl tools exactly when a cluster is configured.

WHAT IT PINS. How the tool modules fit into the one catalogue the model is
given: `core/tools/__init__.py` builds `TOOL_DEFINITIONS` from every tool
module, and lets the four kubectl tools in only when `kubectl.k8s` finds a
cluster (the in-cluster service account, or a kubeconfig file that exists). A
tool that can only fail is noise in every prompt; a cluster the catalogue
misses is a stack the assistant cannot look at. The catalogue is built at
import, so each case imports it in a fresh interpreter with the case's
environment.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The four names
are the kubectl module map's, written here by hand, and each environment is
made up so its answer is plain from the rule: a service host, or a kubeconfig
file the test wrote, means all four; an unset or dangling kubeconfig, none.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row lets the
kubectl tools in whatever the box has, so the no-cluster cases offer them.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
KUBECTL_TOOLS = ["kubectl_describe", "kubectl_events", "kubectl_get", "kubectl_logs"]
PRINT_NAMES = (
    "import json; from apps.assistant.core.tools import TOOL_DEFINITIONS as d; "
    "print(json.dumps(sorted(x['name'] for x in d if x['name'].startswith('kubectl_'))))"
)

CASES = [
    pytest.param({"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, None, KUBECTL_TOOLS, id="in-cluster"),
    pytest.param({}, "written", KUBECTL_TOOLS, id="a-kubeconfig-that-exists"),
    pytest.param({}, "dangling", [], id="a-kubeconfig-that-does-not"),
    pytest.param({}, None, [], id="no-cluster-at-all"),
]


@pytest.mark.parametrize("extra, kubeconfig, expected", CASES)
def test_the_catalogue_offers_the_kubectl_tools_exactly_when_a_cluster_is_configured(
        extra: dict, kubeconfig: str | None, expected: list, tmp_path) -> None:
    """The kubectl names in a freshly built catalogue are the hand-written ones."""
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("KUBERNETES_SERVICE_HOST", "KUBECONFIG")}
    environment.update(extra, PYTHONPATH=str(ROOT))
    if kubeconfig is not None:
        path = tmp_path / "kubeconfig"
        if kubeconfig == "written":
            path.write_text("apiVersion: v1\nkind: Config\n")
        environment["KUBECONFIG"] = str(path)
    answer = subprocess.run([sys.executable, "-c", PRINT_NAMES], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=120, check=True)
    assert json.loads(answer.stdout.strip().splitlines()[-1]) == expected
