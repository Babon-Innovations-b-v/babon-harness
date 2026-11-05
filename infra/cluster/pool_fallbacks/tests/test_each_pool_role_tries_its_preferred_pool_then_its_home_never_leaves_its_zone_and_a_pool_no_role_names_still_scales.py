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

THE WARM FLOOR. `warm_floor()` reads the gate role's working-hours count and
turns WORKING_DAYS and WORKING_HOURS into the two cron lines, written out by
hand: cron counts Sunday as 0, a minute comes before the hour, and hours that
end before they start are refused. The count at a moment is the working
count only on a working day from the opening minute up to, not including,
the closing one. Swapping `_DAYS` to start on Monday turns
both floor cases red.

GUARDS. The stock fallback, ported from the cluster foundation (2026-11-04).
"""
from __future__ import annotations

import pytest

from infra.cluster.pool_fallbacks import WarmFloor, fallback_actions, pools, priorities, warm_floor

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

#: The same two zones with a warm gate floor: three nodes 08:30-18:00 on
#: Monday to Friday, the gate's minimum of one otherwise (cron's Monday is 1).
_WARM = {**_TWO_ZONES, "POOL_GATE_WARM": "3", "POOL_GATE_MIN": "1",
         "WORKING_DAYS": "Mon-Fri", "WORKING_HOURS": "08:30-18:00"}
_WARM_FLOOR = WarmFloor(working=3, idle=1, up="30 8 * * 1-5", down="0 18 * * 1-5",
                        days=frozenset({1, 2, 3, 4, 5}), opens=(8, 30), closes=(18, 0))
#: (cron weekday, hour, minute) -> the count the floor asks for then: inside
#: the hours on a working day, the minute they close, before they open, Sunday.
_WARM_MOMENTS = {(3, 8, 30): 3, (5, 17, 59): 3, (2, 18, 0): 1, (1, 8, 29): 1, (0, 12, 0): 1}
#: A list of days, and a floor with no minimum outside working hours.
_WARM_LIST = {**_TWO_ZONES, "POOL_GATE_WARM": "1",
              "WORKING_DAYS": "Mon,Wed,Sun", "WORKING_HOURS": "09:00-17:15"}
_WARM_LIST_FLOOR = WarmFloor(working=1, idle=0, up="0 9 * * 1,3,0", down="15 17 * * 1,3,0",
                             days=frozenset({0, 1, 3}), opens=(9, 0), closes=(17, 15))
#: Hours that end before they start are refused, never a schedule that never runs.
_WARM_BACKWARDS = {**_TWO_ZONES, "POOL_GATE_WARM": "2", "WORKING_DAYS": "Mon-Fri", "WORKING_HOURS": "18:00-08:00"}


@pytest.mark.parametrize(
    ("settings", "live", "expected_pools", "expected_priorities", "expected_actions", "expected_warm"),
    [
        (_TWO_ZONES, _TWO_ZONES_LIVE, _TWO_ZONES_POOLS, _TWO_ZONES_PRIORITIES, _TWO_ZONES_ACTIONS, None),
        (_ONE_POOL, _ONE_POOL_LIVE, _ONE_POOL_POOLS, _ONE_POOL_PRIORITIES, {}, None),
        (_WARM, _TWO_ZONES_LIVE, _TWO_ZONES_POOLS, _TWO_ZONES_PRIORITIES, _TWO_ZONES_ACTIONS, _WARM_FLOOR),
        (_WARM_LIST, _TWO_ZONES_LIVE, _TWO_ZONES_POOLS, _TWO_ZONES_PRIORITIES, _TWO_ZONES_ACTIONS, _WARM_LIST_FLOOR),
        (_WARM_BACKWARDS, _TWO_ZONES_LIVE, _TWO_ZONES_POOLS, _TWO_ZONES_PRIORITIES, _TWO_ZONES_ACTIONS,
         "WORKING_HOURS='18:00-08:00' ends before it starts"),
    ],
    ids=["two-zones-media-pinned", "one-pool-no-fallbacks", "warm-floor-weekdays", "warm-floor-day-list",
         "warm-hours-backwards"],
)
def test_each_pool_role_tries_its_preferred_pool_then_its_home_never_leaves_its_zone_and_a_pool_no_role_names_still_scales(
    settings, live, expected_pools, expected_priorities, expected_actions, expected_warm,
) -> None:
    """The pool table, the expander's order, the fallback actions and the warm floor match the hand-written answer."""
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

    if isinstance(expected_warm, str):
        with pytest.raises(ValueError, match=expected_warm.replace("(", r"\(")):
            warm_floor(settings)
    else:
        assert warm_floor(settings) == expected_warm
    if expected_warm == _WARM_FLOOR:
        for (weekday, hour, minute), count in _WARM_MOMENTS.items():
            assert expected_warm.count_at(weekday, hour, minute) == count, (weekday, hour, minute)
