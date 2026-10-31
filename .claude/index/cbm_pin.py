"""Read `pin.env` and answer the three questions every caller of the binary has.

Which build does this box need, where does it live, and is the file there that
build? `install.sh`, `cbm_index.py`, the MCP server and any repository's own
callers ask here rather than spell the answer themselves, because a path spelled
in five places is a path one installer can silently overwrite.

WHERE IT LIVES. ``<cache>/harness/cbm/<version>/codebase-memory-mcp``, where
``<cache>`` is ``$XDG_CACHE_HOME`` or ``~/.cache``. The version is in the path,
so moving the pin is a new directory rather than an overwrite, and no other
installer writes there.

WHY THE CHECK IS CACHED. The binary is about 330 MB and hashing it costs about a
second. The verdict is remembered in a file beside the binary, keyed on the
binary's size and modification time, so a repeat check is one ``stat`` and one
small read. Any write to the binary changes one of the two and forces a fresh
hash.

Standard library only: this runs on a box with ``python3`` and nothing else.

Command line, for the shell callers::

    python3 cbm_pin.py path     # the pinned binary's path on this box
    python3 cbm_pin.py shell    # CBM_* assignments for this platform, for eval
    python3 cbm_pin.py check    # exit 0 when that path holds the pinned build

FAILURE POLICY: fail loud. An unsupported platform or a pin missing a field
raises ``PinError`` naming what is missing; the command line prints it and
exits 1.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import sys

#: The data file this module reads. Beside it on purpose: the shell installer
#: reads the same values through ``shell``, so the pin is written down once.
PIN_FILE = pathlib.Path(__file__).with_name("pin.env")

#: The executable's file name, inside the tarball and once installed.
BINARY_NAME = "codebase-memory-mcp"

#: The command that installs the pinned build, named in every failure it fixes.
INSTALL = "bash .claude/index/install.sh"

#: How `uname -m` spells a CPU, mapped to how upstream's asset names spell it.
#: Linux on ARM says `aarch64` and macOS says `arm64` for the same thing.
_MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

#: The file beside the binary that remembers it was checked.
_VERDICT = ".verified.json"


class PinError(RuntimeError):
    """The pin cannot name a build for this box."""


@dataclasses.dataclass(frozen=True)
class Build:
    """One platform's pinned build: what to fetch and what it must hash to."""

    version: str
    asset: str
    tarball_sha256: str
    sha256: str


def read(path: pathlib.Path = PIN_FILE) -> dict[str, str]:
    """The ``KEY=value`` lines of a pin file, comments and blanks skipped."""
    fields = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """This box as the pin's keys spell it, such as ``linux_amd64``."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if machine not in _MACHINES:
        raise PinError(f"no pinned build for CPU {machine!r}")
    return f"{system}_{_MACHINES[machine]}"


def build_for(fields: dict[str, str], key: str) -> Build:
    """The pinned build for one platform key, or why there is none."""
    wanted = {"asset": f"CBM_ASSET_{key}",
              "tarball_sha256": f"CBM_TARBALL_SHA256_{key}",
              "sha256": f"CBM_SHA256_{key}"}
    missing = [name for name in ("CBM_VERSION", *wanted.values()) if not fields.get(name)]
    if missing:
        raise PinError(f"pin.env has no build for {key}: missing {', '.join(missing)}")
    return Build(version=fields["CBM_VERSION"],
                 **{attr: fields[name] for attr, name in wanted.items()})


def this_build() -> Build:
    """The pinned build for the box this runs on."""
    return build_for(read(), platform_key())


def install_dir(version: str) -> pathlib.Path:
    """The directory one pinned version is installed into."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return pathlib.Path(base) / "harness" / "cbm" / version


def binary_path(version: str | None = None) -> pathlib.Path:
    """Where the pinned binary lives on this box."""
    return install_dir(version or read()["CBM_VERSION"]) / BINARY_NAME


def sha256_of(path: pathlib.Path) -> str:
    """The hex sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reported_version(binary: pathlib.Path) -> str:
    """What the binary prints for ``--version``, or empty when it cannot run."""
    try:
        done = subprocess.run([str(binary), "--version"], capture_output=True,
                              text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def _stat_key(binary: pathlib.Path) -> dict[str, int]:
    """The two numbers a remembered verdict is keyed on."""
    status = binary.stat()
    return {"size": status.st_size, "mtime_ns": status.st_mtime_ns}


def _remembered(binary: pathlib.Path, build: Build) -> bool:
    """Was this exact file already found to be this build?"""
    try:
        verdict = json.loads(binary.with_name(_VERDICT).read_text())
    except (OSError, ValueError):
        return False
    return verdict == {**_stat_key(binary), "sha256": build.sha256,
                       "version": build.version}


def _remember(binary: pathlib.Path, build: Build) -> None:
    """Record that this exact file is this build. Best effort."""
    verdict = {**_stat_key(binary), "sha256": build.sha256, "version": build.version}
    try:
        binary.with_name(_VERDICT).write_text(json.dumps(verdict))
    except OSError:
        pass


def is_pinned_build(binary: pathlib.Path, build: Build) -> bool:
    """Does this file hash to the pin and report the pinned version?"""
    if sha256_of(binary) != build.sha256:
        return False
    return reported_version(binary).endswith(build.version.lstrip("v"))


def verified(binary: pathlib.Path, build: Build) -> bool:
    """Is the file at ``binary`` the pinned build? Cached on size and mtime."""
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return False
    if _remembered(binary, build):
        return True
    if not is_pinned_build(binary, build):
        return False
    _remember(binary, build)
    return True


def shell_assignments(build: Build) -> str:
    """The pin for this platform as ``KEY=value`` lines a shell can eval."""
    fields = read()
    values = {"CBM_VERSION": build.version, "CBM_ASSET": build.asset,
              "CBM_TARBALL_SHA256": build.tarball_sha256, "CBM_SHA256": build.sha256,
              "CBM_UPSTREAM": fields.get("CBM_UPSTREAM", ""),
              "CBM_BIN": str(binary_path(build.version))}
    return "\n".join(f"{key}='{value}'" for key, value in values.items())


def main(argv: list[str]) -> int:
    """The command line: ``path``, ``shell`` or ``check``."""
    command = argv[0] if argv else ""
    try:
        if command == "path":
            print(binary_path())
            return 0
        build = this_build()
        if command == "shell":
            print(shell_assignments(build))
            return 0
        if command == "check":
            binary = binary_path(build.version)
            if verified(binary, build):
                return 0
            print(f"{binary} is not codebase-memory-mcp {build.version}; run {INSTALL}",
                  file=sys.stderr)
            return 1
    except PinError as error:
        print(error, file=sys.stderr)
        return 1
    print("usage: cbm_pin.py path|shell|check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
