"""The cluster Caddyfile dials a cluster Service for every compose upstream and refuses one it has no Service for.

WHAT IT PINS. `infra.caddy.cluster_caddyfile.render_cluster_caddyfile`, through
the package's public names: every `reverse_proxy` and `forward_auth` upstream
is swapped for its row in the table given, the global options block gains the
`servers` block that reads the load balancer's PROXY header, and an upstream
with no row raises `UnmappedUpstream` instead of rendering.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
synthetic ground truth: a made-up Caddyfile of a few lines, a made-up table
(`web:80` to `web.site.svc:80`, a placeholder upstream to `hook.deploy.svc:9`)
and the output written out by hand from the rules: the generated header, then
the source line for line, with only the upstream word changed and the servers
block placed first inside the source's own global block, or in a new block at
the top when the source has none (Caddy reads only the first block as global).

ONE FUNCTION. Every check is a parametrized case.

WHAT IT WAS PROVED AGAINST. The rewrite kept the compose upstream instead of
the table's, so the rendered file still dials `web:80`.

GUARDS. Services as cluster Deployments (2026-11-04).
"""
from __future__ import annotations

import pytest

from infra.caddy.cluster_caddyfile import UnmappedUpstream, render_cluster_caddyfile

_TABLE = {
    "web:80": "web.site.svc:80",
    "host:{$PORT:9}": "hook.deploy.svc:9",
}

_HEADER = (
    "# GENERATED from infra/caddy/Caddyfile by python3 -m infra.caddy.cluster_caddyfile.\n"
    "# Do not edit: edit that file or cluster_caddyfile/_upstreams.py. Only the\n"
    "# upstreams and the servers block differ; the comments still describe compose.\n"
    "\n"
)

_SERVERS = (
    "\tservers {\n"
    "\t\tlistener_wrappers {\n"
    "\t\t\tproxy_protocol {\n"
    "\t\t\t\tallow 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10\n"
    "\t\t\t}\n"
    "\t\t\ttls\n"
    "\t\t}\n"
    "\t\ttrusted_proxies static private_ranges\n"
    "\t}\n"
)

_WITH_GLOBAL = (
    "# front door\n"
    "{\n"
    "\temail {$ACME_EMAIL}\n"
    "}\n"
    "a.example {\n"
    "\t# reverse_proxy web:80 in a comment stays\n"
    "\treverse_proxy web:80 {\n"
    "\t\theader_down X y\n"
    "\t}\n"
    "\tforward_auth web:80 {\n"
    "\t\turi /auth\n"
    "\t}\n"
    "}\n"
    "b.example {\n"
    "\treverse_proxy host:{$PORT:9}\n"
    "}\n"
)

_WITH_GLOBAL_RENDERED = (
    _HEADER
    + "# front door\n"
    "{\n"
    + _SERVERS
    + "\temail {$ACME_EMAIL}\n"
    "}\n"
    "a.example {\n"
    "\t# reverse_proxy web:80 in a comment stays\n"
    "\treverse_proxy web.site.svc:80 {\n"
    "\t\theader_down X y\n"
    "\t}\n"
    "\tforward_auth web.site.svc:80 {\n"
    "\t\turi /auth\n"
    "\t}\n"
    "}\n"
    "b.example {\n"
    "\treverse_proxy hook.deploy.svc:9\n"
    "}\n"
)

_WITHOUT_GLOBAL = "a.example {\n\treverse_proxy web:80\n}\n"

_WITHOUT_GLOBAL_RENDERED = _HEADER + "{\n" + _SERVERS + "}\n\n" + "a.example {\n\treverse_proxy web.site.svc:80\n}\n"

_UNMAPPED = "{\n}\na.example {\n\treverse_proxy web:80\n\treverse_proxy db:5432\n}\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(_WITH_GLOBAL, _WITH_GLOBAL_RENDERED, id="global-block-kept-and-every-upstream-rewritten"),
        pytest.param(_WITHOUT_GLOBAL, _WITHOUT_GLOBAL_RENDERED, id="no-global-block-gets-one-at-the-top"),
        pytest.param(_UNMAPPED, UnmappedUpstream("line 5: upstream 'db:5432'"), id="unmapped-upstream-refused-with-its-line"),
    ],
)
def test_the_cluster_caddyfile_dials_a_cluster_service_for_every_compose_upstream_and_refuses_one_it_has_no_service_for(
    source: str, expected: str | UnmappedUpstream
) -> None:
    """The source renders to the hand-written cluster file, or is refused naming the line and upstream."""
    if isinstance(expected, UnmappedUpstream):
        with pytest.raises(UnmappedUpstream, match=str(expected)):
            render_cluster_caddyfile(source, _TABLE)
        return
    assert render_cluster_caddyfile(source, _TABLE) == expected
