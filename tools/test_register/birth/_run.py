"""Run test files the way the gate runs them: in its pinned image, sealed.

OWNS: the commit hook's run of the test files a commit adds or changes: inside
the gate image the pin names by digest, with the network off, the wall clock
moved by a fixed offset, and a clean `env -i`.

DOES NOT OWN: which files run (the hook passes them), the pin itself
(`_pin.py` reads `infra/gate-image/pin`), or the static half of the birth check
(`_scan.py`).

WHY THE IMAGE. A test that passes on a dev box and fails in the gate turns an
innocent commit red: a tool the box has and the gate lacks, another python, a
file only this box carries. The hook runs a new test where the gate will.

WHY SEALED. The network is off and the clock runs 10,000 days (about 27 years)
behind, the same offset in every process, so a deadline loop of `date` calls
still ends and a timeout still measures what it should. A test that leans on
either fails here, at birth, instead of in the gate on a later day. The
repository is mounted at its own path, so a worktree's git directory (mounted
read-only) still resolves and the paths in a failure are yours.

FAILURE POLICY. With no docker, no pin, an image it cannot pull, or a lock this
image was not built from (the offline re-sync fails), it returns `CANNOT` and
says why on stderr; the hook then runs the files locally and says so loudly.
Only a run that happened is a verdict.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ._pin import PIN, read_pin

#: The exit code for "this box could not run the sealed check", never a verdict.
CANNOT = 99

#: An offset, never a start date: libfaketime restarts an `@date` clock in every
#: new process, so a shell loop waiting on `date +%s` would never reach its deadline.
FAKE_NOW = "-10000d"
FAKETIME_LIBRARY = "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"

#: Re-points the image's editable workspace members at the mounted tree, from
#: the image's own uv cache with no network, then runs the rest of the argv.
_SYNC_THEN_RUN = (
    'cd "$1" && shift && UV_OFFLINE=1 uv sync --frozen --all-packages --all-extras --all-groups -q '
    f'>/tmp/sealed-sync.log 2>&1 || {{ cat /tmp/sealed-sync.log >&2; exit {CANNOT}; }}; exec "$@"'
)


def sealed_argv(image: str, root: str, git_dir: str, tests: list[str], *, user: str) -> list[str]:
    """The `docker run` that runs `tests` from the tree at `root` in `image`, sealed."""
    mounts = ["-v", f"{root}:{root}"]
    if git_dir and git_dir != root and not git_dir.startswith(f"{root}/"):
        mounts += ["-v", f"{git_dir}:{git_dir}:ro"]
    pytest = [
        "env", "-i", "HOME=/home/gate", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
        f"PYTHONPATH={root}", f"LD_PRELOAD={FAKETIME_LIBRARY}", f"FAKETIME={FAKE_NOW}",
        "timeout", "300", "/opt/gate-env/bin/pytest", "-q", "--no-header", "-p", "no:randomly",
        "-p", "no:cacheprovider", *tests,
    ]
    return [
        "docker", "run", "--rm", "--network", "none", "--user", user, *mounts, "-w", root,
        image, "bash", "-c", _SYNC_THEN_RUN, "sealed", root, *pytest,
    ]


def sealed_run(repo: Path, tests: list[str]) -> int:
    """Run `tests` sealed in the pinned gate image: pytest's own exit code, or `CANNOT`."""
    try:
        image = read_pin((repo / PIN).read_text(encoding="utf-8")).image
    except (OSError, UnicodeDecodeError):
        image = ""
    if not image:
        return _cannot(f"{PIN} names no gate image digest")
    if shutil.which("docker") is None:
        return _cannot("docker is not on PATH")
    if not _image_here(image):
        return _cannot(f"could not pull {image}")
    argv = sealed_argv(image, str(repo), _git_dir(repo), tests, user=f"{os.getuid()}:{os.getgid()}")
    try:
        verdict = subprocess.run(argv, check=False, timeout=420).returncode
    except subprocess.TimeoutExpired:
        return 124
    if verdict == CANNOT:
        return _cannot("the image's environment would not re-sync offline against this tree's lock; "
                       "rebuild it with infra/gate-image/build.sh")
    return verdict


def _cannot(why: str) -> int:
    print(f"sealed run: not run, {why}", file=sys.stderr)
    return CANNOT


def _image_here(image: str) -> bool:
    """The image is on this box, pulling it once when it is not."""
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False).returncode == 0:
        return True
    print(f"sealed run: pulling the gate image once, {image}", file=sys.stderr)
    try:
        return subprocess.run(["docker", "pull", "-q", image], capture_output=True, check=False,
                              timeout=1800).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _git_dir(repo: Path) -> str:
    """The repository's common git directory, so a worktree's `.git` file resolves inside the container."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
