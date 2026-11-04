"""The cluster's Caddyfile, rendered from the compose one by rewriting its upstreams.

Tier S. Module map:

    _upstreams.py   CLUSTER_UPSTREAMS: each compose upstream and the cluster Service that replaces it
    _render.py      render_cluster_caddyfile(source, upstreams): the cluster Caddyfile as text

`infra/caddy/Caddyfile` stays the one file a person edits; the cluster copy is
rendered from it at apply time (`infra/cluster/apply.sh`), so it is never
stale. The command line is `python3 -m infra.caddy.cluster_caddyfile`. Stdlib
only; nothing here reads a live machine.
"""
from __future__ import annotations

from ._render import UnmappedUpstream, render_cluster_caddyfile
from ._upstreams import CLUSTER_UPSTREAMS

__all__ = ["CLUSTER_UPSTREAMS", "UnmappedUpstream", "render_cluster_caddyfile"]
