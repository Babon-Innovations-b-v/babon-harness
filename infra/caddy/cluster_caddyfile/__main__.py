"""python3 -m infra.caddy.cluster_caddyfile [--out PATH]

Renders `infra/caddy/Caddyfile` into the cluster Caddyfile and writes it to
PATH (default `infra/k8s/ingress/Caddyfile`, git-ignored), where the ingress
kustomization turns it into the `caddyfile` ConfigMap. Run from the repository
root; `infra/cluster/apply.sh` runs it before every apply.

Exit 0 written, 2 an upstream has no cluster Service.

FAILURE POLICY: Tier 1 loud. An unreadable source or unwritable target raises.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from infra.caddy.cluster_caddyfile import CLUSTER_UPSTREAMS, UnmappedUpstream, render_cluster_caddyfile

SOURCE = Path("infra/caddy/Caddyfile")
TARGET = Path("infra/k8s/ingress/Caddyfile")


def main(argv: list[str]) -> int:
    """Render the cluster Caddyfile and write it."""
    parser = argparse.ArgumentParser(prog="python3 -m infra.caddy.cluster_caddyfile")
    parser.add_argument("--out", type=Path, default=TARGET)
    args = parser.parse_args(argv)
    try:
        rendered = render_cluster_caddyfile(SOURCE.read_text(encoding="utf-8"), CLUSTER_UPSTREAMS)
    except UnmappedUpstream as error:
        print(f"cluster_caddyfile: {error}", file=sys.stderr)
        return 2
    args.out.write_text(rendered, encoding="utf-8")
    print(f"cluster_caddyfile: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
