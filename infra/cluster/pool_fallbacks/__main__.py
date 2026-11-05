"""python3 -m infra.cluster.pool_fallbacks --pools
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --priorities
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --fallback-actions
python3 -m infra.cluster.pool_fallbacks --warm

Reads the settings from the environment (`set -a; . config/harness.env`).
`--pools` prints every pool of every role as a JSON list in the order the
autoscaler tries them. `--priorities` prints the expander's ConfigMap as JSON.
`--fallback-actions` prints one `<pool> <create|ok|recreate|has-nodes>` line
per fallback pool. `--warm` prints `<working> <idle> <now>` (now: the count
the floor asks for this minute in ASSISTANT_TIMEZONE), then the up and the
down cron line; `0 0 0` and two empty lines when there is no warm floor.

FAILURE POLICY: Tier 1 loud. A missing setting or bad JSON on stdin raises.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from infra.cluster.pool_fallbacks import WarmFloor, fallback_actions, pools, priorities, warm_floor


def _warm_lines(floor: WarmFloor | None, settings: dict) -> str:
    """The `--warm` answer, the count for now read on the settings' clock."""
    if floor is None:
        return "0 0 0\n\n"
    now = datetime.now(ZoneInfo(settings.get("ASSISTANT_TIMEZONE") or "UTC"))
    count = floor.count_at(now.isoweekday() % 7, now.hour, now.minute)
    return f"{floor.working} {floor.idle} {count}\n{floor.up}\n{floor.down}"


def main(argv: list[str]) -> int:
    """Print the pool list, the expander's ConfigMap, the fallback actions or the warm floor."""
    parser = argparse.ArgumentParser(prog="python3 -m infra.cluster.pool_fallbacks")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pools", action="store_true")
    mode.add_argument("--priorities", action="store_true")
    mode.add_argument("--fallback-actions", action="store_true")
    mode.add_argument("--warm", action="store_true")
    args = parser.parse_args(argv)
    settings = dict(os.environ)
    if args.warm:
        floor = warm_floor(settings)
        print(_warm_lines(floor, settings))
    elif args.pools:
        print(json.dumps([dataclasses.asdict(spec) for spec in pools(settings)]))
    elif args.fallback_actions:
        for name, action in fallback_actions(settings, json.load(sys.stdin)).items():
            print(name, action)
    else:
        print(json.dumps(priorities(settings, json.load(sys.stdin))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
