"""Each pool role tries its preferred pool first, then its home zone, never leaves its zone set, and a pool no role names still scales.

WHAT IT PINS. `infra.cluster.pool_fallbacks`: `pools()` (every pool of every
role, read from the settings), `priorities()` (the cluster autoscaler priority
expander's ConfigMap built from a live pool list) and `fallback_actions()`
(what the cluster script does to each fallback it finds live), through the
package's public names only.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
synthetic ground truth: made-up settings (zones `zone-a` and `zone-b`, machine
types `small`, `medium` and `card`) and a made-up live pool list, with the
answer written out by hand from the rules. The order within a role: the
preferred type in the home zone, its other types in the home zone, then the
preferred type in the other zones, then the rest; a role whose zone set is one
zone stays there. A role's taint is none (0), the role label (the default)
or the `key=value` it names. The expander contract (upstream cluster-autoscaler): a higher
number wins, regexes match node group ids, a node group no regex matches is
never used, so `.*` at 1 sits below every role pool. The weights are ten per
rank below the deepest role's depth. A provider cannot resize a root disk, so a
fallback on the wrong disk is recreated only while it has no nodes; the disk is
written in bytes the way the provider reports it (100GB = 100000000000).

WHAT IT WAS PROVED AGAINST. The weight turned from falling with the rank to
rising with it, so a fallback outranks its preferred pool.

GUARDS. The stock fallback, ported from the cluster foundation (2026-11-04).
"""
from __future__ import annotations

import pytest

from infra.cluster.pool_fallbacks import fallback_actions, pools, priorities

_TWO_ZONES = {
    "CLUSTER_ZONES": "zone-a,zone-b",
    "POOL_ROLES": "system,media",
    "POOL_ROLE_LABEL": "example/role",
    "POOL_SYSTEM_TYPES": "small,medium",
    "POOL_SYSTEM_MIN": "1",
    "POOL_SYSTEM_MAX": "3",
    "POOL_SYSTEM_DISK": "100GB",
    "POOL_SYSTEM_TAINT": "0",
    "POOL_MEDIA_TYPES": "small,medium",
    "POOL_MEDIA_ZONES": "zone-a",
    "POOL_MEDIA_MIN": "0",
    "POOL_MEDIA_MAX": "1",
    "POOL_MEDIA_DISK": "40GB",
    "POOL_MEDIA_SHARED_SECURITY_GROUP": "1",
}
_MEDIA_TAINT = (("example/role", "media", "NoSchedule"),)
#: (name, type, zone, rank, min, max, disk, taints, shared security group)
_TWO_ZONES_POOLS = [
    ("system", "small", "zone-a", 0, 1, 3, "100GB", (), False),
    ("system-medium-zone-a", "medium", "zone-a", 1, 0, 3, "100GB", (), False),
    ("system-small-zone-b", "small", "zone-b", 2, 0, 3, "100GB", (), False),
    ("system-medium-zone-b", "medium", "zone-b", 3, 0, 3, "100GB", (), False),
    ("media", "small", "zone-a", 0, 0, 1, "40GB", _MEDIA_TAINT, True),
    ("media-medium-zone-a", "medium", "zone-a", 1, 0, 1, "40GB", _MEDIA_TAINT, True),
]
_SMALL, _BIG = 40_000_000_000, 100_000_000_000
_TWO_ZONES_LIVE = [
    {"name": "system", "id": "id-system", "size": 2, "root_volume_size": _BIG},
    {"name": "system-medium-zone-a", "id": "id-sm-a", "size": 0, "root_volume_size": _SMALL},
    {"name": "system-small-zone-b", "id": "id-ss-b", "size": 1, "root_volume_size": _SMALL},
    {"name": "system-medium-zone-b", "id": "id-sm-b", "size": 1, "root_volume_size": _BIG},
    {"name": "media", "id": "id-media", "size": 1, "root_volume_size": _SMALL},
    {"name": "made-by-hand", "id": "id-hand", "size": 0, "root_volume_size": _BIG},
]
_TWO_ZONES_PRIORITIES = """40:
  - ^id-media$
  - ^id-system$
30:
  - ^id-sm-a$
20:
  - ^id-ss-b$
10:
  - ^id-sm-b$
1:
  - .*
"""
_TWO_ZONES_ACTIONS = {
    "system-medium-zone-a": "recreate",
    "system-small-zone-b": "has-nodes",
    "system-medium-zone-b": "ok",
    "media-medium-zone-a": "create",
}

_ONE_POOL = {
    "CLUSTER_ZONES": "zone-a",
    "POOL_ROLES": "gpu",
    "POOL_ROLE_LABEL": "example/role",
    "POOL_GPU_TYPES": "card",
    "POOL_GPU_MIN": "0",
    "POOL_GPU_MAX": "2",
    "POOL_GPU_DISK": "125GB",
    "POOL_GPU_TAINT": "workload=transcribe",
}
_ONE_POOL_POOLS = [
    ("gpu", "card", "zone-a", 0, 0, 2, "125GB", (("workload", "transcribe", "NoSchedule"),), False),
]
_ONE_POOL_LIVE = [
    {"name": "gpu", "id": "id-gpu", "size": 0, "root_volume_size": 125_000_000_000},
    {"name": "made-by-hand", "id": "id-hand", "size": 0, "root_volume_size": _BIG},
]
_ONE_POOL_PRIORITIES = "10:\n  - ^id-gpu$\n1:\n  - .*\n"


@pytest.mark.parametrize(
    ("settings", "live", "expected_pools", "expected_priorities", "expected_actions"),
    [
        (_TWO_ZONES, _TWO_ZONES_LIVE, _TWO_ZONES_POOLS, _TWO_ZONES_PRIORITIES, _TWO_ZONES_ACTIONS),
        (_ONE_POOL, _ONE_POOL_LIVE, _ONE_POOL_POOLS, _ONE_POOL_PRIORITIES, {}),
    ],
    ids=["two-zones-media-pinned", "one-pool-no-fallbacks"],
)
def test_each_pool_role_tries_its_preferred_pool_then_its_home_never_leaves_its_zone_and_a_pool_no_role_names_still_scales(
    settings, live, expected_pools, expected_priorities, expected_actions,
) -> None:
    """The pool table, the expander's order and the fallback actions match the hand-written answer."""
    got_pools = [
        (spec.name, spec.node_type, spec.zone, spec.rank, spec.min_size, spec.max_size,
         spec.root_volume_size, spec.taints, spec.shared_security_group)
        for spec in pools(settings)
    ]
    assert got_pools == expected_pools
    for spec in pools(settings):
        assert spec.labels == (("example/role", spec.role),), f"{spec.name} lacks its role label"

    configmap = priorities(settings, live)
    assert configmap["metadata"] == {"name": "cluster-autoscaler-priority-expander", "namespace": "kube-system"}
    assert configmap["data"]["priorities"] == expected_priorities

    assert fallback_actions(settings, live) == expected_actions
