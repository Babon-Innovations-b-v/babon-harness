"""Every pool of every pool role, preferred first, read from the settings.

OWNS: turning the `POOL_*` and `CLUSTER_ZONES` lines of `config/harness.env`
into pool specs and their order. DOES NOT OWN: what is done to a live pool
(`_actions.py`) or the expander's ranking (`_priorities.py`).

A role names its machine types (first preferred) and its zone set (first is
the home zone). Its order: the preferred type in the home zone, the other
types in the home zone (a pod with a zonal volume can only follow there), then
the preferred type in the other zones of the set, then the other types there. A role whose zone set is one zone
never leaves it. Every pool of a role carries the role label, the role's taint
when it has one (`POOL_<ROLE>_TAINT`: 0 none, 1 the role label as taint, or
`key=value`), and the role's root disk, so a pod that selects the role can
land on any of them.

FAILURE POLICY: Tier 1 loud. A role with a missing or malformed line raises
ValueError naming the key; a wrong pool is worse than none.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolSpec:
    """One pool of a role: its shape and its place in the role's order (0 = preferred)."""

    name: str
    role: str
    node_type: str
    zone: str
    rank: int
    min_size: int
    max_size: int
    root_volume_size: str
    labels: tuple[tuple[str, str], ...]
    taints: tuple[tuple[str, str, str], ...]
    #: Create it in the preferred pool's security group, not the zone's default.
    shared_security_group: bool


def _required(settings: Mapping[str, str], key: str) -> str:
    """The non-empty value of `key`, or ValueError naming it."""
    value = (settings.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is empty in config/harness.env")
    return value


def _listed(value: str) -> list[str]:
    """'a, b,,c' -> ['a', 'b', 'c']."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _number(settings: Mapping[str, str], key: str) -> int:
    """The whole number in `key`, or ValueError naming it."""
    value = _required(settings, key)
    if not value.isdigit():
        raise ValueError(f"{key}={value!r} is not a whole number")
    return int(value)


def _flag(settings: Mapping[str, str], key: str, default: str) -> bool:
    """1 or 0 in `key`, `default` when empty."""
    value = (settings.get(key) or default).strip()
    if value not in ("0", "1"):
        raise ValueError(f"{key}={value!r} is not 0 or 1")
    return value == "1"


def _taints(value: str, label: str, role: str) -> tuple[tuple[str, str, str], ...]:
    """0 = none, 1 = `<label>=<role>:NoSchedule`, `key=value` = that taint, NoSchedule."""
    value = value.strip()
    if value == "0":
        return ()
    if value == "1":
        return ((label, role, "NoSchedule"),)
    key, equals, taint_value = value.partition("=")
    if not equals or not key or not taint_value:
        raise ValueError(f"POOL_{role.upper()}_TAINT={value!r} is not 0, 1 or key=value")
    return ((key, taint_value, "NoSchedule"),)


def _order(node_types: list[str], zones: list[str]) -> list[tuple[str, str]]:
    """(node type, zone) in the order the autoscaler should try them."""
    home_zone, other_zones = zones[0], zones[1:]
    order = [(node_type, home_zone) for node_type in node_types]
    for node_type in node_types:
        order.extend((node_type, zone) for zone in other_zones)
    return order


def _role_pools(settings: Mapping[str, str], role: str) -> list[PoolSpec]:
    """The pools of one role, preferred first."""
    prefix = f"POOL_{role.upper()}_"
    node_types = _listed(_required(settings, prefix + "TYPES"))
    zones = _listed(settings.get(prefix + "ZONES") or "") or _listed(_required(settings, "CLUSTER_ZONES"))
    label = _required(settings, "POOL_ROLE_LABEL")
    taints = _taints(settings.get(prefix + "TAINT") or "1", label, role)
    shared_group = _flag(settings, prefix + "SHARED_SECURITY_GROUP", "0")
    min_size, max_size = _number(settings, prefix + "MIN"), _number(settings, prefix + "MAX")
    disk = _required(settings, prefix + "DISK")
    specs = []
    for rank, (node_type, zone) in enumerate(_order(node_types, zones)):
        name = role if rank == 0 else f"{role}-{node_type.lower()}-{zone}"
        specs.append(PoolSpec(
            name=name, role=role, node_type=node_type, zone=zone, rank=rank,
            min_size=min_size if rank == 0 else 0, max_size=max_size,
            root_volume_size=disk, labels=((label, role),), taints=taints,
            shared_security_group=shared_group,
        ))
    return specs


def pools(settings: Mapping[str, str]) -> list[PoolSpec]:
    """Every pool of every role in `POOL_ROLES`, each role's preferred pool (rank 0) first."""
    return [spec for role in _listed(_required(settings, "POOL_ROLES")) for spec in _role_pools(settings, role)]
