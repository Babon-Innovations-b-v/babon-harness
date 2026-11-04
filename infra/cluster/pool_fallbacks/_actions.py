"""What the cluster script does to each fallback pool it finds live.

OWNS: the create, ok, recreate or has-nodes decision per fallback. DOES NOT
OWN: the pool list (`_pools.py`) or the provider calls, which are
`infra/cluster/create-cluster.sh`'s.

A provider cannot resize a pool's root disk, so a live fallback whose disk is
not its role's is deleted and created again, but only while it has no nodes:
deleting one with nodes would evict what runs there.

FAILURE POLICY: Tier 1 loud. A live pool that lacks a field raises KeyError.
"""
from __future__ import annotations

from collections.abc import Mapping

from ._pools import pools


def _bytes(size: str) -> int:
    """'100GB' -> 100_000_000_000, the bytes the provider reports for a root disk."""
    if not size.endswith("GB") or not size[:-2].isdigit():
        raise ValueError(f"root disk size {size!r} is not written as <N>GB")
    return int(size[:-2]) * 10**9


def fallback_actions(settings: Mapping[str, str], live_pools: list[dict]) -> dict[str, str]:
    """Fallback pool name -> create, ok, recreate or has-nodes, given the live pool list."""
    live = {pool["name"]: pool for pool in live_pools}
    actions = {}
    for spec in pools(settings):
        if spec.rank == 0:
            continue
        pool = live.get(spec.name)
        if pool is None:
            actions[spec.name] = "create"
        elif int(pool["root_volume_size"]) == _bytes(spec.root_volume_size):
            actions[spec.name] = "ok"
        elif int(pool["size"]) == 0:
            actions[spec.name] = "recreate"
        else:
            actions[spec.name] = "has-nodes"
    return actions
