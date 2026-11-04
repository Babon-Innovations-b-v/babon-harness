"""python3 -m infra.deploy_loop <verb> ...: the deploy loop's questions to the cluster.

Verbs, each one question:

    receive                      run the push receiver (settings from the environment)
    bookmark-read                print ConfigMap deploy-bookmark's sha ('' = none yet); exit 2 refused
    bookmark-write SHA           set it
    gate-run [options] -- ARGS   run pytest ARGS in a gate Job, or one Job per shard with
                                 --shards-file; exit with the verdict code they add up to
    image-targets IMAGE          print `namespace kind name container` for each object to re-pin
    stack-images REPO            print `name context dockerfile` for each of the stack's own images

The one file in this package that runs kubectl or reads a clock; everything it
decides is asked of the pure modules beside it.

FAILURE POLICY: gate-run never exits 0 to 5 for a fault of its own: a Job it
could not create or read is 125, and a pin that names no image is 125 (AMBER).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from ._bookmark import bookmark_sha
from ._gate_job import gate_job_manifest, pinned_gate_image
from ._images import stack_images
from ._outcome import RC_COULD_NOT_START, gate_job_outcome
from ._pins import image_targets
from ._receiver import serve
from ._shards import combined_rc, read_shards

_NAMESPACE = os.environ.get("DEPLOY_NAMESPACE", "deploy")
_POLL_SECONDS = 10


def _kubectl(*args: str, stdin: str = "", timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "-n", _NAMESPACE, *args], input=stdin or None, capture_output=True,
                          text=True, errors="replace", timeout=timeout, check=False)


def _receive(_: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    wanted = [name.strip() for name in os.environ.get("DEPLOY_RECEIVER_CRONJOBS", "deploy-cycle,commit-gate").split(",")
              if name.strip()]
    serve(int(os.environ.get("PORT", "9000")), os.environ.get("DEPLOY_WEBHOOK_SECRET", ""), _NAMESPACE, wanted)
    return 0


def _bookmark_read(_: argparse.Namespace) -> int:
    answer = _kubectl("get", "configmap", "deploy-bookmark", "-o", "json")
    if answer.returncode != 0:
        print(f"bookmark-read: {answer.stderr.strip()}", file=sys.stderr)
        return 2
    try:
        print(bookmark_sha(json.loads(answer.stdout)))
    except ValueError as refused:
        print(f"bookmark-read: {refused}", file=sys.stderr)
        return 2
    return 0


def _bookmark_write(args: argparse.Namespace) -> int:
    bookmark_sha({"data": {"sha": args.sha}})
    patch = json.dumps({"data": {"sha": args.sha}})
    answer = _kubectl("patch", "configmap", "deploy-bookmark", "--type", "merge", "-p", patch)
    if answer.returncode != 0:
        print(f"bookmark-write: {answer.stderr.strip()}", file=sys.stderr)
    return answer.returncode


def _job_state(name: str) -> tuple:
    job = _kubectl("get", "job", name, "-o", "json")
    pods = _kubectl("get", "pods", "-l", f"job-name={name}", "-o", "json")
    if job.returncode != 0 or pods.returncode != 0:
        return None, None
    return json.loads(job.stdout), json.loads(pods.stdout).get("items") or []


def _append_logs(name: str, log_path: str, replay_rc_file: str) -> None:
    answer = _kubectl("logs", f"job/{name}", "--all-containers", "--prefix=false", timeout=120)
    replay_rc = ""
    with open(log_path, "a", encoding="utf-8") as log:
        for line in answer.stdout.splitlines():
            if line.startswith("@@replay-rc@@ "):
                replay_rc = line.split()[-1]
                continue
            log.write(line.removeprefix("@@replay@@ ") + "\n")
    if replay_rc_file and replay_rc:
        Path(replay_rc_file).write_text(replay_rc + "\n", encoding="utf-8")


def _gate_run(args: argparse.Namespace) -> int:
    try:
        gate_image = pinned_gate_image(Path(args.gate_pin).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        gate_image = ""
    if not gate_image:
        print(f"gate-run: {args.gate_pin} names no gate image digest; build one with infra/gate-image/build.sh",
              file=sys.stderr)
        return RC_COULD_NOT_START
    changed = Path(args.changed_file).read_text(encoding="utf-8") if args.changed_file else ""
    shards = _shards_of(args.shards_file)
    if shards is None:
        return RC_COULD_NOT_START
    # One Job per shard, all made at once; the break replay runs in the first
    # one only, because it replays every row the commit touches whatever the
    # shard holds. No shards file: one Job for the whole run, as before.
    runs = [(name, [*args.pytest_args, *paths]) for name, paths in shards] or [("all", list(args.pytest_args))]
    stamp = int(time.time())
    names = []
    for index, (shard, pytest_args) in enumerate(runs):
        name = f"gate-{args.sha[:12]}-{stamp}-{index}" if len(runs) > 1 else f"gate-{args.sha[:12]}-{stamp}"
        manifest = gate_job_manifest(
            name=name, namespace=_NAMESPACE, sha=args.sha, repo_url=args.repo_url, gate_image=gate_image,
            cycle_image=args.cycle_image, pool_label=args.pool_label, pytest_args=pytest_args,
            seconds=args.seconds, setup_seconds=args.setup_seconds, changed_paths=changed if index == 0 else "",
            replay_workers=args.replay_workers, ref=args.ref, cpu=args.cpu, memory=args.memory,
        )
        created = _kubectl("apply", "-f", "-", stdin=json.dumps(manifest))
        if created.returncode != 0:
            print(f"gate-run: could not create Job {name}: {created.stderr.strip()}", file=sys.stderr)
            return RC_COULD_NOT_START
        print(f"gate-run: Job {name} runs {args.sha[:12]} ({shard}) in {gate_image}", file=sys.stderr)
        names.append(name)
    verdicts = _wait_for(names, args)
    if args.log:
        for name in names:
            _append_logs(name, args.log, args.replay_rc_file)
    return combined_rc([verdicts[name] for name in names])


def _shards_of(path: str) -> list | None:
    """The shards a shards file names, [] for none given, None when it cannot be read."""
    if not path:
        return []
    try:
        return read_shards(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as failure:
        print(f"gate-run: cannot read the shards file {path}: {failure}", file=sys.stderr)
        return None


def _wait_for(names: list, args: argparse.Namespace) -> dict:
    """Each Job's verdict code once it ends, or a timeout once the run's deadline has passed."""
    deadline = time.monotonic() + args.seconds + args.setup_seconds + 60
    verdicts: dict = {}
    while True:
        timed_out = time.monotonic() > deadline
        for name in names:
            if name in verdicts:
                continue
            job, pods = _job_state(name)
            verdict = gate_job_outcome(job, pods, timed_out, args.pin_is_new) if job is not None else None
            if verdict is None and timed_out:
                verdict = RC_COULD_NOT_START if job is None else 124
            if verdict is not None:
                verdicts[name] = verdict
        if len(verdicts) == len(names):
            return verdicts
        time.sleep(_POLL_SECONDS)


def _image_targets(args: argparse.Namespace) -> int:
    answer = subprocess.run(["kubectl", "get", "deployments,statefulsets,daemonsets,cronjobs", "-A", "-o", "json"],
                            capture_output=True, text=True, timeout=60, check=False)
    if answer.returncode != 0:
        print(f"image-targets: {answer.stderr.strip()}", file=sys.stderr)
        return 2
    for target in image_targets([json.loads(answer.stdout)], args.image):
        print(" ".join(target))
    return 0


def _stack_images(args: argparse.Namespace) -> int:
    for image in stack_images(Path(args.repo)):
        print(image["name"], image["context"] or "-", image["dockerfile"] or "-")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m infra.deploy_loop")
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("receive").set_defaults(run=_receive)
    verbs.add_parser("bookmark-read").set_defaults(run=_bookmark_read)
    write = verbs.add_parser("bookmark-write")
    write.add_argument("sha")
    write.set_defaults(run=_bookmark_write)
    gate = verbs.add_parser("gate-run")
    gate.add_argument("--sha", required=True)
    gate.add_argument("--ref", default="")
    gate.add_argument("--repo-url", required=True)
    gate.add_argument("--gate-pin", required=True, help="the GATED tree's infra/gate-image/pin")
    gate.add_argument("--pin-is-new", action="store_true", help="the gated commit changed the pin")
    gate.add_argument("--cycle-image", required=True)
    gate.add_argument("--pool-label", required=True)
    gate.add_argument("--seconds", type=int, required=True)
    gate.add_argument("--setup-seconds", type=int, default=900)
    gate.add_argument("--changed-file", default="")
    gate.add_argument("--replay-workers", type=int, default=1)
    gate.add_argument("--replay-rc-file", default="")
    gate.add_argument("--cpu", default="2")
    gate.add_argument("--memory", default="6Gi")
    gate.add_argument("--log", default="")
    gate.add_argument("--shards-file", default="",
                      help="`<shard>\\t<path>` lines (test_register --shards): one Job per shard, at once")
    gate.add_argument("pytest_args", nargs="+")
    gate.set_defaults(run=_gate_run)
    targets = verbs.add_parser("image-targets")
    targets.add_argument("image")
    targets.set_defaults(run=_image_targets)
    images = verbs.add_parser("stack-images")
    images.add_argument("repo")
    images.set_defaults(run=_stack_images)
    return parser


def main(argv: list | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
