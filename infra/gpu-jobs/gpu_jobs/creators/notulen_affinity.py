"""The node affinity of a notulen GPU pod: one of the notulen pools, earlier first.

The notulen Job and the GPU placeholder a recording holds share it with
``notulen_tolerations``, so the placeholder never warms a node the Job cannot
use.

A node pool lives in one zone, so a single-pool pin waits for as long as that
zone is out of GPU stock. This affinity accepts every pool ``GPU_POOL``
lists. Among nodes that already exist, the preferred terms steer the pod to
the earlier pool. The autoscaler does not move to another pool by itself
while it still counts an out-of-stock node as on its way; deleting that node
is what moves the next scale-up.

FAILURE POLICY: pure manifest building, no I/O; a malformed ``GPU_POOL``
raises ValueError from the accessor.
"""

from __future__ import annotations

from kubernetes import client

from ..config.notulen_pool import notulen_pool_names, pool_label


def notulen_affinity() -> client.V1Affinity:
    """Required: one of the notulen pools. Preferred: earlier pools first."""
    pools = notulen_pool_names()
    label = pool_label()
    return client.V1Affinity(
        node_affinity=client.V1NodeAffinity(
            required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                node_selector_terms=[
                    client.V1NodeSelectorTerm(
                        match_expressions=[
                            client.V1NodeSelectorRequirement(
                                key=label, operator="In", values=list(pools),
                            ),
                        ],
                    ),
                ],
            ),
            preferred_during_scheduling_ignored_during_execution=[
                client.V1PreferredSchedulingTerm(
                    weight=100 // (rank + 1),
                    preference=client.V1NodeSelectorTerm(
                        match_expressions=[
                            client.V1NodeSelectorRequirement(
                                key=label, operator="In", values=[pool],
                            ),
                        ],
                    ),
                )
                for rank, pool in enumerate(pools)
            ],
        ),
    )
