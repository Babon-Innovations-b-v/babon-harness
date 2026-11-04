"""Turn the compose Caddyfile into the cluster one.

OWNS: `render_cluster_caddyfile()`, a pure text transform. DOES NOT OWN: the
table (`_upstreams.py`) or writing the file (`__main__.py`).

Two things change and nothing else. The upstream word of every
`reverse_proxy` and `forward_auth` line becomes the cluster Service from the
table. And the global options block gains a `servers` block: the cloud load
balancer in front of the cluster may send a PROXY protocol v2 header (a
provider annotation on the `caddy` Service), and Caddy reads the client
address from it, so the address Nextcloud throttles logins by is the user's
and not a node's. It is accepted only from private ranges, where the load
balancer and the nodes sit; a connection without the header (a probe, a
caller inside the cluster) is still served. The source's own global block
keeps its options; a source without one gets a new block at the top, because
Caddy reads only the first block as global.

FAILURE POLICY: fail closed. An upstream with no row in the table raises
`UnmappedUpstream`, so a site added to the compose Caddyfile cannot render
into a cluster config that dials nothing.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

HEADER = (
    "# GENERATED from infra/caddy/Caddyfile by python3 -m infra.caddy.cluster_caddyfile.\n"
    "# Do not edit: edit that file or cluster_caddyfile/_upstreams.py. Only the\n"
    "# upstreams and the servers block differ; the comments still describe compose.\n"
    "\n"
)

SERVERS_BLOCK = (
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

_DIRECTIVE = re.compile(r"^(?P<lead>\s*(?:reverse_proxy|forward_auth)\s+)(?P<upstream>\S+)(?P<rest>[^\r\n]*)")


class UnmappedUpstream(ValueError):
    """An upstream in the compose Caddyfile has no cluster Service in the table."""


def render_cluster_caddyfile(source: str, upstreams: Mapping[str, str]) -> str:
    """Return the cluster Caddyfile: the source with its upstreams rewritten and the servers block added."""
    lines = [_rewrite(line, number, upstreams) for number, line in enumerate(source.splitlines(keepends=True), start=1)]
    return HEADER + _with_servers_block(lines)


def _rewrite(line: str, number: int, upstreams: Mapping[str, str]) -> str:
    match = _DIRECTIVE.match(line)
    if match is None:
        return line
    upstream = match.group("upstream")
    if upstream not in upstreams:
        raise UnmappedUpstream(
            f"line {number}: upstream {upstream!r} has no cluster Service; "
            "add it to infra/caddy/cluster_caddyfile/_upstreams.py"
        )
    ending = line[len(line.rstrip("\r\n")):]
    return match.group("lead") + upstreams[upstream] + match.group("rest") + ending


def _with_servers_block(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "{":
            return "".join(lines[: index + 1]) + SERVERS_BLOCK + "".join(lines[index + 1 :])
        break
    return "{\n" + SERVERS_BLOCK + "}\n\n" + "".join(lines)
