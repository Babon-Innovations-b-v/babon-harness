"""Carry the commit-gate lane's answers to the deploy cycle, one way.

The lane (CronJob `commit-gate`) and the cycle (CronJob `deploy-cycle`) run in
different pods with different ReadWriteOnce volumes, so the lane packs what it
wrote into ONE ConfigMap (`commit-gate-verdicts`) and step 18 of the cycle
unpacks it. Neither pod can write the other's volume.

    pack    lane state dir + the shas still queued -> a ConfigMap document on stdout
    unpack  that ConfigMap, as `kubectl get -o json` prints it, on stdin
            -> the cycle's state dir, never replacing a file already there

Only the commits between the bookmark and `origin/main` are packed, so the map
stays small (a ConfigMap holds at most 1 MiB) and a commit the deploy has
passed drops out by itself. The cycle reads on every tick, so a file is copied
long before it drops out.

UNPACK NEVER REPLACES A FILE. A verdict the cycle already holds was written by
a run the cycle can account for, possibly the one it shipped on.

Stdlib only: the cycle pod runs this with the image's system python from its
clone, before any venv exists.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

#: key prefix -> (drawer under the state dir, file suffix), in the order they
#: are packed. The verdict decides whether a commit ships, so it goes first and
#: is never the one cut for size; the rest are what a hand-back quotes, what
#: tells the cycle's eject arm the lane already decided, and the record the
#: nightly audit reads.
DRAWERS = {
    "v": ("gate-verdicts", ""),
    "d": ("eject-decisions", ""),
    "t": ("gate-red-tails", ""),
    "s": ("gate-scopes", ".json"),
    "r": ("gate-runs", ".json"),
}

#: Under the API server's 1 MiB object limit, with room for the metadata.
MAX_BYTES = 900_000

_SHA = re.compile(r"^[0-9a-f]{40}$")
_KEY = re.compile(r"^([a-z])\.([0-9a-f]{40})$")


def pack(state_dir: Path, shas: list, name: str, namespace: str) -> tuple[dict, list]:
    """The ConfigMap holding every drawer file for `shas`, and the keys cut for size."""
    data: dict = {}
    cut: list = []
    size = 0
    wanted = [sha for sha in shas if _SHA.match(sha)]
    for prefix, (drawer, suffix) in DRAWERS.items():
        for sha in wanted:
            path = state_dir / drawer / f"{sha}{suffix}"
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            key = f"{prefix}.{sha}"
            if size + len(body) + len(key) > MAX_BYTES:
                cut.append(key)
                continue
            data[key] = body
            size += len(body) + len(key)
    document = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/name": "commit-gate"},
        },
        "data": data,
    }
    return document, cut


def unpack(document: dict, state_dir: Path) -> tuple[int, list]:
    """Write every file the cycle does not have yet; the count written and keys refused."""
    written = 0
    refused: list = []
    for key, body in sorted((document.get("data") or {}).items()):
        match = _KEY.match(key)
        if not match or match.group(1) not in DRAWERS or not isinstance(body, str):
            refused.append(key)
            continue
        prefix, sha = match.groups()
        if prefix == "v" and body.split(" ", 1)[0] != sha:
            refused.append(key)
            continue
        drawer, suffix = DRAWERS[prefix]
        target = state_dir / drawer / f"{sha}{suffix}"
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f"{target.name}.lane.{os.getpid()}")
        staged.write_text(body, encoding="utf-8")
        # A link, not a rename: it fails when the cycle wrote the same file in
        # between, and the cycle's copy is the one that stands.
        try:
            os.link(staged, target)
            written += 1
        except FileExistsError:
            pass
        finally:
            staged.unlink(missing_ok=True)
    return written, refused


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    packing = verbs.add_parser("pack")
    packing.add_argument("--state-dir", required=True, type=Path)
    packing.add_argument("--shas-file", required=True, type=Path)
    packing.add_argument("--name", required=True)
    packing.add_argument("--namespace", required=True)
    unpacking = verbs.add_parser("unpack")
    unpacking.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.verb == "pack":
        shas = args.shas_file.read_text(encoding="utf-8").split()
        document, cut = pack(args.state_dir, shas, args.name, args.namespace)
        if cut:
            print(f"lane_drawers: {len(cut)} file(s) left out for size: {' '.join(cut)}", file=sys.stderr)
        json.dump(document, sys.stdout)
        return 0

    try:
        document = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(f"lane_drawers: the lane's ConfigMap is not JSON ({error}); nothing copied", file=sys.stderr)
        return 1
    written, refused = unpack(document, args.state_dir)
    if refused:
        print(f"lane_drawers: refused {len(refused)} key(s) that name no drawer file: {' '.join(refused)}", file=sys.stderr)
    print(written)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
