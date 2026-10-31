"""The repository's code index: built on first use, atomically, stamped, asked through the cli.

WHAT. codebase-memory-mcp parses a repository into a graph of files, symbols and
calls. This module keeps that index for the shared checkout of the repository it
sits in, and asks it one question at a time through the pinned binary's plain
cli (`cbm_pin.py` says which binary). Nothing is left running: each cli call
starts the tool's daemon for the length of the call and it exits about a second
later. The MCP server beside this file and any repository's own tools call the
same functions.

WHY THE SHARED CHECKOUT. The tool keys a project on its root path, so indexing a
worktree opens a second near-copy of the whole index. Every worktree is asked
about the checkout its git common directory belongs to, and an answer to a
worktree says how far that checkout is from it.

WHY A PRIVATE DIRECTORY AND A RENAME. The tool writes its database in place. A
reader arriving mid-build would get a half-written index whose empty answers
read as true absences. So the build runs with ``CBM_CACHE_DIR`` pointed at a
private directory beside the real cache, the stamp is the last write, and only
then is the file renamed over the live one. A rename on one filesystem is
atomic: a reader sees the old index or the new one. The tool's watcher is a
config key stored in the cache directory, so it is switched off in the private
directory only.

THE STAMP. A table ``index_stamp`` in the index, one row per project: the commit
the build saw and when. A reader treats an index without it as not built, and
an index stamped for another commit as due a rebuild. A repository that writes
its own rows into the index after the tool's (``passes``) keeps its own stamp
as well; this one only says the tool's half is whole.

WHY A LOCK. Two sessions asking their first question at once must not both
build the same file. The second waits on the lock and finds the first one's.

Standard library only: this runs on a box with ``python3`` and nothing else.

Command line::

    python3 .claude/index/cbm_index.py build [ROOT]   # rebuild now

FAILURE POLICY: fail loud. Every failure raises ``BuildError`` carrying its
cause and the one command that fixes it; ``ready`` and ``ask`` turn it into an
answer with ``error`` and ``fix`` and never an empty result. Nothing is renamed
into place unless every step succeeded and the result holds rows.
"""
from __future__ import annotations

import datetime
import fcntl
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cbm_pin  # noqa: E402 - the sibling module, found through the line above

#: The checkout this file sits in: `.claude/index/` is two levels below it.
REPO = HERE.parents[1]

#: The command that rebuilds by hand, named in every failure a rebuild fixes.
REBUILD = "python3 .claude/index/cbm_index.py build"

#: The command that clears a daemon of another version, which refuses ours.
CLEAR_DAEMON = "pkill -f codebase-memory-mcp"

#: The table the stamp lives in, inside the index itself so it moves with it.
STAMP_TABLE = "index_stamp"

#: Longest one build step may take. A large repository indexes in under a
#: minute; ten is a hang, not a slow box.
_STEP_TIMEOUT = 600

#: Longest one question may take. A cold call is a few seconds.
_ASK_TIMEOUT = 120


class BuildError(RuntimeError):
    """An index that could not be built or asked, with its cause and its fix."""

    def __init__(self, cause: str, fix: str) -> None:
        super().__init__(f"{cause}. Fix: {fix}")
        self.cause = cause
        self.fix = fix


def cache_dir() -> pathlib.Path:
    """Where the tool keeps its indexes: ``CBM_CACHE_DIR``, else its default.

    The binary ignores ``XDG_CACHE_HOME`` for this, so this does too.
    """
    return pathlib.Path(os.environ.get("CBM_CACHE_DIR")
                        or pathlib.Path.home() / ".cache/codebase-memory-mcp")


def shared_checkout(here: pathlib.Path) -> pathlib.Path:
    """The checkout the index is built from, which is never a worktree.

    A worktree's git common directory is ``<shared>/.git``, so its parent is
    the shared checkout; in the shared checkout that is already true. Raises
    ``subprocess.CalledProcessError`` outside a git checkout.
    """
    common = subprocess.run(
        ["git", "-C", str(here), "rev-parse", "--path-format=absolute",
         "--git-common-dir"],
        capture_output=True, check=True, text=True, timeout=30,
    ).stdout.strip()
    return pathlib.Path(common).parent


def project_for(root: pathlib.Path | str) -> str:
    """The name the tool keys an index on, derived from its root path.

    Every run of non-alphanumeric characters becomes ONE dash, which is what the
    tool itself does. Replacing each character separately looks identical on a
    plain path and names an index that was never written for any path with a
    dot directory in it.
    """
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(root).lstrip("/")).strip("-")


def project_name(root: pathlib.Path) -> str:
    """The project this checkout's index is kept under.

    ``index_project`` in ``.claude/project.json`` when the repository sets one,
    else the root path's name (``project_for``). The path is the safe default:
    two clones of one repository on one box then keep separate indexes.
    """
    try:
        settings = json.loads((root / ".claude/project.json").read_text())
    except (OSError, ValueError):
        settings = {}
    named = settings.get("index_project") if isinstance(settings, dict) else None
    return named if isinstance(named, str) and named else project_for(root)


def head_of(root: pathlib.Path) -> str:
    """The commit a checkout is on, or empty when git cannot say."""
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30,
                              check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def stamp_of(database: pathlib.Path, project: str) -> str:
    """The commit a finished build stamped on this index, or empty when unstamped."""
    if not database.exists():
        return ""
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error:
        return ""
    try:
        row = connection.execute(
            f"SELECT head FROM {STAMP_TABLE} WHERE project = ?", (project,)).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
    # A build where git could not answer stamps an empty head; it is still a
    # finished build, so it reads as stamped.
    return (row[0] or "unknown") if row else ""


def write_stamp(database: pathlib.Path, project: str, head: str) -> None:
    """Stamp a finished index with the commit it was built from. The last write."""
    connection = sqlite3.connect(database)
    try:
        connection.execute(f"CREATE TABLE IF NOT EXISTS {STAMP_TABLE} "
                           "(project TEXT PRIMARY KEY, head TEXT, built_at TEXT)")
        connection.execute(
            f"INSERT OR REPLACE INTO {STAMP_TABLE} VALUES (?, ?, ?)",
            (project, head, datetime.datetime.now(datetime.timezone.utc).isoformat()))
        connection.commit()
    finally:
        connection.close()


def run_step(command: list[str], env: dict[str, str],
             cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Run one build step, capturing its output; a timeout reads as a failed step."""
    try:
        return subprocess.run(command, env=env, cwd=str(cwd or REPO),
                              capture_output=True, text=True,
                              timeout=_STEP_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "",
                                           f"timed out after {_STEP_TIMEOUT} s")
    except OSError as failed:
        return subprocess.CompletedProcess(command, 127, "", str(failed))


def tail_of(done: subprocess.CompletedProcess) -> str:
    """The last lines a failed step printed, which usually name the cause."""
    text = (done.stderr or "").strip() or (done.stdout or "").strip()
    return " | ".join(text.splitlines()[-3:]) or f"exit {done.returncode}"


def ensure_binary() -> pathlib.Path:
    """The pinned binary, installed first when it is missing or not the pin."""
    try:
        build = cbm_pin.this_build()
    except cbm_pin.PinError as failed:
        raise BuildError(f"no pinned codebase-memory-mcp for this box: {failed}",
                         "add this platform to .claude/index/pin.env") from failed
    binary = cbm_pin.binary_path(build.version)
    if cbm_pin.verified(binary, build):
        return binary
    done = run_step(["bash", str(HERE / "install.sh")], os.environ.copy())
    if done.returncode != 0 or not cbm_pin.verified(binary, build):
        raise BuildError(
            f"codebase-memory-mcp {build.version} is not installed at {binary} and "
            f"installing it failed: {tail_of(done)}", cbm_pin.INSTALL)
    return binary


def index_into(binary: pathlib.Path, root: pathlib.Path, project: str,
               env: dict[str, str], rebuild: str = REBUILD) -> None:
    """The tool's index of ``root``, written into the cache ``env`` names."""
    for key in ("watcher_enabled", "auto_watch"):
        run_step([str(binary), "config", "set", key, "false"], env)
    done = run_step([str(binary), "cli", "--quiet", "index_repository",
                     "--repo-path", str(root), "--name", project], env)
    if done.returncode == 0:
        return
    cause = tail_of(done)
    fix = (CLEAR_DAEMON + ", then ask again"
           if "conflicting" in cause.lower() or "daemon" in cause.lower() else rebuild)
    raise BuildError(f"codebase-memory-mcp could not index {root}: {cause}", fix)


def row_count(database: pathlib.Path, project: str, label: str | None = None) -> int:
    """How many nodes an index holds for this project, of one label if given."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    query = "SELECT count(*) FROM nodes WHERE project = ?" + (" AND label = ?" if label else "")
    try:
        return connection.execute(query, (project, label) if label else (project,)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


def _placed(built: pathlib.Path, target: pathlib.Path) -> None:
    """Rename the finished file over the live one."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # A journal left beside the old file would be replayed onto the new one.
    for suffix in ("-wal", "-shm", "-journal"):
        pathlib.Path(f"{target}{suffix}").unlink(missing_ok=True)
    os.replace(built, target)


def _assembled(root: pathlib.Path, project: str, scratch: pathlib.Path,
               seed: pathlib.Path | None, passes, rebuild: str) -> pathlib.Path:
    """Run the whole chain inside ``scratch`` and return the stamped file."""
    built = scratch / f"{project}.db"
    if seed is not None and seed.exists():
        # The tool indexes incrementally against the file hashes it stored, so
        # starting from the live index costs only the files that changed.
        shutil.copy2(seed, built)
    env = {**os.environ, "CBM_CACHE_DIR": str(scratch)}
    index_into(ensure_binary(), root, project, env, rebuild)
    if passes is not None:
        passes(built, root, project, env)
    if not row_count(built, project):
        raise BuildError(f"the build of {root} wrote no rows", rebuild)
    # Last write of the build, after every row it vouches for is in place.
    write_stamp(built, project, head_of(root))
    return built


def build(root: pathlib.Path | None = None, *, force: bool = False, passes=None,
          incremental: bool = False, rebuild: str = REBUILD) -> pathlib.Path:
    """Build the index for a checkout's shared checkout, atomically.

    Args:
        root: any checkout or worktree of the repository; the index is always
            built against its shared checkout.
        force: rebuild even when the index is already stamped for this commit.
        passes: optional ``passes(built, root, project, env)``, run after the
            tool's index and before the stamp, for a repository that writes its
            own rows into the index; it raises ``BuildError`` to refuse.
        incremental: start from a copy of the live index, so only changed files
            are parsed. Off when ``passes`` would write their rows twice.
        rebuild: the command named as the fix when a rebuild is the fix.

    Returns:
        The path of the finished index.

    Raises:
        BuildError: with the cause and the one command that fixes it.
    """
    root = shared_checkout(root or REPO)
    project = project_name(root)
    target = cache_dir() / f"{project}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.parent / f".{project}.build.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Built by the session that held the lock before us, for this commit.
        head, stamp = head_of(root), stamp_of(target, project)
        if not force and stamp and (not head or stamp == head):
            return target
        scratch = target.parent.parent / f".cbm-build.{project}.{os.getpid()}"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        try:
            seed = target if incremental else None
            _placed(_assembled(root, project, scratch, seed, passes, rebuild), target)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return target


def worktree_lag(here: pathlib.Path, shared: pathlib.Path) -> str:
    """One line on how far the shared checkout, which the index describes, is from here.

    Empty in the shared checkout itself, and when git cannot say.
    """
    try:
        if pathlib.Path(here).resolve() == pathlib.Path(shared).resolve():
            return ""
        theirs = subprocess.run(["git", "-C", str(shared), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10,
                                check=True).stdout.strip()
        counts = subprocess.run(
            ["git", "-C", str(here), "rev-list", "--left-right", "--count",
             f"{theirs}...HEAD"],
            capture_output=True, text=True, timeout=10, check=True).stdout.split()
        behind, ahead = int(counts[0]), int(counts[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return ""
    return (f"Asked from a worktree: the index describes the shared checkout, which "
            f"is {ahead} commits behind this worktree and {behind} ahead of it; "
            "uncommitted work here is not in it.")


def ready(here: pathlib.Path | None = None) -> dict:
    """The index for this checkout, built or brought up to its commit, or why not.

    Returns:
        ``path``, ``project`` and ``head``, plus ``rebuilt`` when this call
        built it and ``worktree`` when asked from one; or ``error`` with the
        cause and ``fix`` with the one command that repairs it.
    """
    where = pathlib.Path(here or REPO)
    try:
        shared = shared_checkout(where)
    except (OSError, subprocess.SubprocessError) as failed:
        return {"error": f"{where} is not inside a git checkout ({failed})",
                "fix": "start the session inside a clone of the repository"}
    project = project_name(shared)
    target = cache_dir() / f"{project}.db"
    head = head_of(shared)
    place = {"path": str(target), "project": project, "head": head}
    stamp = stamp_of(target, project)
    if not stamp or (head and stamp != head):
        try:
            build(shared, incremental=True)
        except BuildError as failed:
            return {"error": f"the index could not be built: {failed.cause}",
                    "fix": failed.fix}
        except Exception as failed:  # noqa: BLE001 - reported, never raised
            return {"error": f"building the index crashed: {failed!r}", "fix": REBUILD}
        place["rebuilt"] = True
    lag = worktree_lag(where, shared)
    if lag:
        place["worktree"] = lag
    return place


def ask(tool: str, arguments: dict, rebuild: str = REBUILD) -> dict:
    """Run one cli tool with these arguments and return its answer.

    Args:
        tool: the upstream tool name, such as ``query_graph``.
        arguments: its arguments, ``project`` included; ``None`` values dropped.
        rebuild: the command named as the fix when a rebuild is the fix.

    Returns:
        ``ok`` and ``result`` (the tool's own JSON, or its text where it gave
        no JSON); or ``ok: false`` with ``error`` and ``fix``. Never raises.
    """
    try:
        binary = ensure_binary()
    except BuildError as failed:
        return {"ok": False, "error": failed.cause, "fix": failed.fix}
    given = {key: value for key, value in arguments.items() if value is not None}
    try:
        done = subprocess.run(
            [str(binary), "cli", "--quiet", "--json", tool, json.dumps(given)],
            capture_output=True, text=True, timeout=_ASK_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as failed:
        return {"ok": False, "error": f"{binary} could not be run: {failed!r}",
                "fix": cbm_pin.INSTALL}
    return _read(done, rebuild)


def _read(done: subprocess.CompletedProcess, rebuild: str) -> dict:
    """The cli's JSON envelope as an answer, or the cause when there is none."""
    try:
        envelope = json.loads(done.stdout)
    except ValueError:
        cause = (done.stderr or done.stdout or "").strip()[-600:] or f"exit {done.returncode}"
        fix = (CLEAR_DAEMON + ", then ask again"
               if "conflicting" in cause.lower() else rebuild)
        return {"ok": False, "error": f"codebase-memory-mcp gave no answer: {cause}",
                "fix": fix}
    result = envelope.get("structuredContent")
    if result is None:
        text = "".join(part.get("text", "") for part in envelope.get("content") or [])
        try:
            result = json.loads(text)
        except ValueError:
            result = text
    if envelope.get("isError"):
        return {"ok": False, "error": result,
                "fix": "correct the arguments; the error names what was wrong"}
    return {"ok": True, "result": result}


def main(argv: list[str]) -> int:
    """``build [ROOT]``: rebuild now; print where it landed, or the cause and the fix."""
    if not argv or argv[0] != "build":
        print("usage: cbm_index.py build [ROOT]", file=sys.stderr)
        return 2
    root = pathlib.Path(argv[1]) if len(argv) > 1 else None
    try:
        print(f"built {build(root, force=True)}")
    except BuildError as failed:
        print(f"index build failed: {failed.cause}\nfix: {failed.fix}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
