"""The gate image pin: which image the gate runs tests in, and whether it is behind.

OWNS: reading `infra/gate-image/pin` (the image by digest, and the commit it
was built from) and naming the image inputs that moved since that commit.

DOES NOT OWN: building the image (`infra/gate-image/build.sh` writes the pin),
or running a test in it (`_run.py`).

THE FORMAT. Comment lines start with `#`; one of them is `# built from: <sha>`.
The last other line is the reference, and it names an image only when it
carries `@sha256:`: a tag can be moved under the gate, a digest cannot. A pin
that names nothing means no gate image yet, and every reader says so.

THE DRIFT NOTICE. The image holds the locked environment, so it goes stale
when `uv.lock`, any `pyproject.toml`, or the gate image's own Dockerfile moves
past the commit it was built from. `pin_drift` names those files; it is a
notice for whoever rebuilds, never a verdict.

FAILURE POLICY. Never raises. A git that cannot answer, or no built-from line,
is no drift found.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Where the pin lives, repository-relative.
PIN = "infra/gate-image/pin"

#: The image's inputs, as git pathspecs.
INPUTS = ("uv.lock", ":(glob)**/pyproject.toml", "infra/gate-image/Dockerfile",
          "infra/gate-image/Dockerfile.dockerignore")


@dataclass(frozen=True)
class Pin:
    """The image by digest (empty when the pin names none) and the commit it was built from."""

    image: str
    built_from: str


def read_pin(text: str) -> Pin:
    """The pin file's image reference and built-from commit."""
    built_from, reference = "", ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped.lower().startswith("# built from:"):
                built_from = stripped.split(":", 1)[1].strip()
            continue
        if stripped:
            reference = stripped
    return Pin(image=reference if "@sha256:" in reference else "", built_from=built_from)


def pin_drift(repo: Path, built_from: str, revision: str = "HEAD") -> tuple[str, ...]:
    """The image inputs that changed between `built_from` and `revision`, sorted."""
    if not built_from:
        return ()
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", built_from, revision, "--", *INPUTS],
            capture_output=True, text=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if done.returncode != 0:
        return ()
    return tuple(sorted(line for line in done.stdout.splitlines() if line.strip()))
