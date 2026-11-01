"""Give back the disk the index leaves behind: stale tree indexes, old binaries, leftovers.

WHAT. One function, ``sweep``, meant for session start. It removes:

- a tree index whose working tree is gone, or that nothing has touched for
  ``IDLE_DAYS``. A tree index is the convention a repository's tree layer keeps:
  a directory ``<cache parent>/codebase-memory-mcp-trees/<project>/`` holding a
  ``meta.json`` whose ``root`` names the tree, and the index itself at
  ``<cache>/<project>.db``. Each is a few hundred megabytes, and a reaped
  worktree never comes back for its copy;
- every installed binary version other than the one ``pin.env`` names, under
  ``<cache>/harness/cbm/`` and any older install roots the caller names (the
  pinned version is kept in those too, for a stale checkout still reading
  there), unless a running process was started from it. Each is about 330 MB;
- leftovers of a killed build or download older than ``LEFTOVER_SECONDS``: a
  private build or fetch directory, a tree's scratch files, whose names end in
  the pid that made them, when that pid is gone; and a build lock nobody holds;
- the head of any append-only log the caller names, past its last ``keep``
  lines.

WHY IT IS CHEAP. Nothing is hashed or walked unless it is about to go: a quiet
box costs a handful of ``listdir`` and ``stat`` calls, well under 50 ms.

Standard library only.

FAILURE POLICY: fail-open. It runs at session start, so every error is
swallowed and the entry is left for the next session; it returns only what it
actually removed.
"""
from __future__ import annotations

import fcntl
import os
import pathlib
import re
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cbm_index  # noqa: E402 - the sibling module, found through the line above
import cbm_pin  # noqa: E402 - the sibling module, found through the line above

#: A tree index nobody has touched for this long is dropped; its next question rebuilds it.
IDLE_DAYS = 3

#: A leftover younger than this may belong to a build still running.
LEFTOVER_SECONDS = 3600

#: Where tree indexes keep their records, beside the binary's cache.
TREES = "codebase-memory-mcp-trees"

#: A name ending in the pid of the process that made it, with an optional suffix.
_PID = re.compile(r"\.(\d+)(\.[a-z]+)?$")


def sweep(now: float | None = None, older_roots: tuple[pathlib.Path, ...] = (),
          capped: tuple[tuple[pathlib.Path, int], ...] = ()) -> list[tuple[str, int]]:
    """Remove what is stale and return each removed path with the bytes it held.

    Args:
        now: the time to judge ages against; the clock by default.
        older_roots: install roots of earlier layouts, each holding one
            directory per version, swept like the current one.
        capped: ``(log, keep)`` pairs: each log is cut to its last ``keep`` lines.
    """
    now = time.time() if now is None else now
    removed: list[tuple[str, int]] = []
    for step in (_trees, _leftovers):
        try:
            removed += step(now)
        except OSError:
            continue
    try:
        removed += _versions(older_roots)
    except (OSError, cbm_pin.PinError):
        pass
    for log, keep in capped:
        try:
            removed += _cut(log, keep)
        except OSError:
            continue
    return removed


def _cut(log: pathlib.Path, keep: int) -> list[tuple[str, int]]:
    """Keep a log's last ``keep`` lines; read only once it is long enough to need it."""
    if not log.is_file() or log.stat().st_size < keep * 80:
        return []
    lines = log.read_bytes().splitlines(keepends=True)
    if len(lines) <= keep:
        return []
    kept = b"".join(lines[-keep:])
    scratch = log.with_name(f".{log.name}.{os.getpid()}")
    scratch.write_bytes(kept)
    freed = log.stat().st_size - len(kept)
    os.replace(scratch, log)
    return [(str(log), freed)]


def _trees(now: float) -> list[tuple[str, int]]:
    """Tree indexes whose tree is gone or idle for ``IDLE_DAYS``."""
    base = cbm_index.cache_dir().parent / TREES
    if not base.is_dir():
        return []
    removed = []
    for directory in base.iterdir():
        if not directory.is_dir():
            continue
        live = cbm_index.cache_dir() / f"{directory.name}.db"
        root = _root_of(directory)
        gone = root is not None and not pathlib.Path(root).is_dir()
        if gone or now - _newest(directory, live) > IDLE_DAYS * 86400:
            removed += _removed(directory)
            for suffix in ("", "-wal", "-shm", "-journal"):
                removed += _removed(pathlib.Path(f"{live}{suffix}"))
    return removed


def _root_of(directory: pathlib.Path) -> str | None:
    """The tree a tree index was made for, as its ``meta.json`` records it."""
    import json

    try:
        return json.loads((directory / "meta.json").read_text()).get("root")
    except (OSError, ValueError, AttributeError):
        return None


def _newest(directory: pathlib.Path, live: pathlib.Path) -> float:
    """The latest modification of a tree index's record, its files or its placed index."""
    times = [directory.stat().st_mtime]
    for path in [*directory.iterdir(), live]:
        try:
            times.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(times)


def _versions(older_roots: tuple[pathlib.Path, ...]) -> list[tuple[str, int]]:
    """Installed binary versions other than the pin, none of them running."""
    pinned = cbm_pin.read()["CBM_VERSION"]
    current = cbm_pin.install_dir(pinned).parent
    candidates = [path for root in (current, *older_roots) if root.is_dir()
                  for path in root.iterdir()
                  if path.is_dir() and path.name != pinned]
    if not candidates:
        return []
    running = _running_executables()
    removed = []
    for path in candidates:
        if any(str(exe).startswith(f"{path}{os.sep}") for exe in running):
            continue
        removed += _removed(path)
    return removed


def _running_executables() -> set[str]:
    """The executable of every process this user can see, where ``/proc`` says."""
    found = set()
    for entry in pathlib.Path("/proc").glob("[0-9]*") if pathlib.Path("/proc").is_dir() else []:
        try:
            found.add(os.readlink(entry / "exe"))
        except OSError:
            continue
    return found


def _leftovers(now: float) -> list[tuple[str, int]]:
    """Old private build and fetch directories, tree scratch files and unheld build locks."""
    removed = []
    parent, cache = cbm_index.cache_dir().parent, cbm_index.cache_dir()
    places = [path for path in parent.glob(".cbm-*") if _PID.search(path.name)]
    trees = parent / TREES
    if trees.is_dir():
        places += [path for directory in trees.iterdir() if directory.is_dir()
                   for path in directory.glob(".*") if _PID.search(path.name)]
    for path in places:
        if _old(path, now) and not _alive(int(_PID.search(path.name).group(1))):
            removed += _removed(path)
    for lock in cache.glob(".*.build.lock") if cache.is_dir() else []:
        if _old(lock, now) and _unheld(lock):
            removed += _removed(lock)
    return removed


def _old(path: pathlib.Path, now: float) -> bool:
    """Was this last modified more than ``LEFTOVER_SECONDS`` ago?"""
    try:
        return now - path.stat().st_mtime > LEFTOVER_SECONDS
    except OSError:
        return False


def _alive(pid: int) -> bool:
    """Is a process with this pid running?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _unheld(lock: pathlib.Path) -> bool:
    """Can the lock be taken right now, meaning no build holds it?"""
    try:
        with open(lock, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
    except OSError:
        return False


def _removed(path: pathlib.Path) -> list[tuple[str, int]]:
    """Delete one file or directory; return it with its size, or nothing when it was not there."""
    try:
        if path.is_dir() and not path.is_symlink():
            size = sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
            shutil.rmtree(path)
        else:
            size = path.lstat().st_size
            path.unlink()
    except OSError:
        return []
    return [(str(path), size)]
