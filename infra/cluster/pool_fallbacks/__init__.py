"""Which pools stand in for each pool role when the provider is out of stock.

Tier S. Module map:

    _pools.py       pools(settings): every pool of every role, in the order the autoscaler tries them
    _actions.py     fallback_actions(settings, live): create, ok, recreate or has-nodes per fallback
    _priorities.py  priorities(settings, live): the priority expander's ConfigMap
    _warm.py        warm_floor(settings): gate nodes kept up in working hours, and when

`settings` is the environment of `config/harness.env` (a mapping of its keys);
`live` is the provider's pool list as JSON (`scw k8s pool list -o json`). The
command line is `python3 -m infra.cluster.pool_fallbacks`, called by
`infra/cluster/create-cluster.sh`, and `--warm` by `infra/cluster/apply.sh`. Stdlib only; nothing here reads a live
machine.
"""
from __future__ import annotations

from ._actions import fallback_actions
from ._pools import PoolSpec, pools
from ._priorities import PRIORITY_CONFIGMAP, priorities
from ._warm import WarmFloor, warm_floor

__all__ = ["PRIORITY_CONFIGMAP", "PoolSpec", "WarmFloor", "fallback_actions", "pools", "priorities", "warm_floor"]
