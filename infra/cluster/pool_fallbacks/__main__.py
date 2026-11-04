"""python3 -m infra.cluster.pool_fallbacks --pools
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --priorities
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --fallback-actions

Reads the settings from the environment (`set -a; . config/harness.env`).
`--pools` prints every pool of every role as a JSON list in the order the
autoscaler tries them. `--priorities` prints the expander's ConfigMap as JSON.
`--fallback-actions` prints one `<pool> <create|ok|recreate|has-nodes>` line
per fallback pool.

FAILURE POLICY: Tier 1 loud. A missing setting or bad JSON on stdin raises.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from infra.cluster.pool_fallbacks import fallback_actions, pools, priorities


def main(argv: list[str]) -> int:
    """Print the pool list, the expander's ConfigMap or the fallback actions."""
    parser = argparse.ArgumentParser(prog="python3 -m infra.cluster.pool_fallbacks")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pools", action="store_true")
    mode.add_argument("--priorities", action="store_true")
    mode.add_argument("--fallback-actions", action="store_true")
    args = parser.parse_args(argv)
    settings = dict(os.environ)
    if args.pools:
        print(json.dumps([dataclasses.asdict(spec) for spec in pools(settings)]))
    elif args.fallback_actions:
        for name, action in fallback_actions(settings, json.load(sys.stdin)).items():
            print(name, action)
    else:
        print(json.dumps(priorities(settings, json.load(sys.stdin))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
