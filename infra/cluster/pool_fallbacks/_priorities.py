"""The cluster autoscaler priority expander's ConfigMap, ranked from the settings.

OWNS: the weights. DOES NOT OWN: the pool list (`_pools.py`) or applying the
ConfigMap (`infra/cluster/create-cluster.sh`).

The expander reads regexes over node group ids, and on Kapsule a node group's
id is the pool id, so the ConfigMap is rebuilt from the live list after any
pool is created. A higher number wins. Within a role, rank 0 gets the highest
number and every later rank one step less, so a fallback is tried only after
the preferred pool failed to get a node. `.*` at 1 sits below every role pool:
the expander never uses a node group no regex matches, so without it a pool no
role names (one made by hand) would never scale.

FAILURE POLICY: Tier 1 loud. A live pool that lacks a field raises KeyError.
"""
from __future__ import annotations

from collections.abc import Mapping

from ._pools import pools

PRIORITY_CONFIGMAP = "cluster-autoscaler-priority-expander"
_STEP = 10
_CATCH_ALL_PRIORITY = 1


def priorities(settings: Mapping[str, str], live_pools: list[dict]) -> dict:
    """The ConfigMap for the pools in `live_pools` that a role names, plus the catch-all."""
    specs = pools(settings)
    deepest = max((spec.rank for spec in specs), default=0) + 1
    weights = {spec.name: _STEP * (deepest - spec.rank) for spec in specs}
    tiers: dict[int, list[str]] = {_CATCH_ALL_PRIORITY: [".*"]}
    for pool in live_pools:
        if pool["name"] in weights:
            tiers.setdefault(weights[pool["name"]], []).append(f"^{pool['id']}$")
    lines = []
    for weight in sorted(tiers, reverse=True):
        lines.append(f"{weight}:")
        lines.extend(f"  - {pattern}" for pattern in sorted(tiers[weight]))
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": PRIORITY_CONFIGMAP, "namespace": "kube-system"},
        "data": {"priorities": "\n".join(lines) + "\n"},
    }
