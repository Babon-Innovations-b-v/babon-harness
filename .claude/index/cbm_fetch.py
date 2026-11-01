"""Install a committed index another machine built, instead of building it here.

WHAT. A repository whose deploy box already builds the index of each main commit
can publish it as one file on a GitHub release, overwritten each time. This
module downloads that file with ``gh``, checks the commit it describes, renames
it to this checkout's project and puts it in place as the committed index, the
same file ``cbm_index.build`` would have written. A box then answers its first
question in seconds rather than after a build of half a minute or more.

THE FILE. One zstd-compressed SQLite index, the tool's own schema, carrying
``cbm_index``'s stamp table with exactly one row: the project it was built as
and the commit it describes. The release asset's label is that commit, so a box
that already has an index reads the offer with one API call before deciding to
download; a box with none downloads straight away and checks the file's own
stamp, which saves that call on the first question.

WHAT IS CHECKED, in order, and any failure raises ``FetchError`` and places
nothing:

- the offered commit is this checkout's HEAD or an ancestor of it, so the index
  never describes code this checkout does not have; the commits between it and
  HEAD are the caller's to layer on top (they differ from the index's stored
  file hashes like any other changed file);
- it is newer than the index already here, never older;
- the downloaded file's own stamp names that commit;
- the repository's own check (``accept``), for rows of its own it requires.

WHY A RENAME. The tool keys every row on a project name derived from the root
path, and qualified names start with it. The publisher's path is not this one,
so the project and the qualified-name prefix are rewritten to this checkout's,
and the project's root path is pointed here so the text search reads these
files. The full-text table is contentless and cannot be rewritten: its
qualified-name column still holds the publisher's path words, which a search
for those exact words would match.

Standard library plus ``gh`` and, for the decompression, Python 3.14's
``compression.zstd`` or the ``zstd`` command.

FAILURE POLICY: fail loud to the caller. Every refusal raises ``FetchError``
with its cause; the caller falls back to building locally. Nothing is placed
unless every check passed, and the placing is ``cbm_index``'s atomic rename
under its build lock.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cbm_index  # noqa: E402 - the sibling module, found through the line above

#: Longest the offer lookup or the download may take before it reads as failed.
_GH_TIMEOUT = 120


class FetchError(RuntimeError):
    """A published index that was not installed, with the reason."""


def offered(slug: str, tag: str, asset: str) -> str:
    """The commit the published asset describes (its label), read with one gh call."""
    done = _gh(["release", "view", tag, "-R", slug, "--json", "assets"])
    try:
        assets = json.loads(done.stdout).get("assets") or []
    except ValueError as failed:
        raise FetchError(f"gh answered no JSON for release {tag}") from failed
    for one in assets:
        if one.get("name") == asset and one.get("label"):
            return one["label"].strip()
    raise FetchError(f"release {tag} of {slug} has no {asset} carrying a commit label")


def is_ancestor(root: pathlib.Path, older: str, newer: str) -> bool:
    """Is commit ``older`` reachable from ``newer`` (or the same)? False when unknown here."""
    done = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True, timeout=30, check=False)
    return done.returncode == 0


def commits_between(root: pathlib.Path, older: str, newer: str) -> int:
    """How many commits ``newer`` has that ``older`` does not."""
    done = subprocess.run(["git", "-C", str(root), "rev-list", "--count", f"{older}..{newer}"],
                          capture_output=True, text=True, timeout=30, check=False)
    return int(done.stdout.strip() or 0) if done.returncode == 0 else -1


def fetch(root: pathlib.Path | None = None, *, slug: str, tag: str, asset: str,
          accept=None) -> dict:
    """Download the published index and install it as this checkout's committed index.

    Args:
        root: any checkout or worktree; the index is the shared checkout's.
        slug: ``owner/name`` of the repository whose release carries the file.
        tag: the release's tag.
        asset: the file's name on the release.
        accept: optional ``accept(database, project, head)``, run on the
            downloaded file before the rename; raises ``FetchError`` to refuse.

    Returns:
        ``path``, ``project``, ``head`` (the commit installed) and ``behind``
        (commits HEAD has that the index does not).

    Raises:
        FetchError: with the reason nothing was installed.
    """
    shared = cbm_index.shared_checkout(root or cbm_index.REPO)
    project = cbm_index.project_name(shared)
    target = cbm_index.cache_dir() / f"{project}.db"
    head = cbm_index.head_of(shared)
    have = cbm_index.stamp_of(target, project)
    if have and have == head:
        raise FetchError("the index here already describes HEAD")
    commit = offered(slug, tag, asset) if have else ""
    if commit:
        _check_offer(shared, commit, head, have)
    scratch = cbm_index.cache_dir().parent / f".cbm-fetch.{project}.{os.getpid()}"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        _gh(["release", "download", tag, "-R", slug, "-p", asset, "-D", str(scratch), "--clobber"])
        database = scratch / f"{project}.db"
        unzstd(scratch / asset, database)
        theirs, commit = _verified(database, commit)
        _check_offer(shared, commit, head, have)
        if accept is not None:
            accept(database, theirs, commit)
        rename_project(database, theirs, project, qualified=True)
        _rooted(database, project, shared)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target.parent / f".{project}.build.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            # A build that held the lock before us may have placed a newer one.
            _check_offer(shared, commit, head, cbm_index.stamp_of(target, project))
            cbm_index._placed(database, target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"path": str(target), "project": project, "head": commit,
            "behind": commits_between(shared, commit, head)}


def _check_offer(shared: pathlib.Path, commit: str, head: str, have: str) -> None:
    """Refuse an offer this checkout does not contain, or one no newer than what is here."""
    if not head or not is_ancestor(shared, commit, head):
        raise FetchError(f"the published index describes {commit[:12]}, which is not "
                         f"HEAD or an ancestor of it here")
    if have and have != "unknown" and is_ancestor(shared, commit, have):
        raise FetchError(f"the index here ({have[:12]}) is as new as the published one")


def _gh(arguments: list[str]) -> subprocess.CompletedProcess:
    """Run one gh command; a missing gh, a refusal or a timeout raises ``FetchError``."""
    try:
        done = subprocess.run(["gh", *arguments], capture_output=True, text=True,
                              timeout=_GH_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as failed:
        raise FetchError(f"gh could not run: {failed}") from failed
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise FetchError(f"gh {arguments[0]} {arguments[1]} failed: "
                         f"{said[-1] if said else f'exit {done.returncode}'}")
    return done


def unzstd(source: pathlib.Path, into: pathlib.Path) -> None:
    """Decompress a zstd file with Python's own module, else the ``zstd`` command."""
    try:
        from compression import zstd  # Python 3.14 and later
    except ImportError:
        zstd = None
    if zstd is not None:
        with zstd.open(source, "rb") as packed, open(into, "wb") as plain:
            shutil.copyfileobj(packed, plain, 1 << 22)
        return
    if shutil.which("zstd") is None:
        raise FetchError("cannot decompress: neither Python 3.14's compression.zstd "
                         "nor the zstd command is on this box")
    done = subprocess.run(["zstd", "-d", "-q", "-f", str(source), "-o", str(into)],
                          capture_output=True, text=True, timeout=300, check=False)
    if done.returncode != 0:
        raise FetchError(f"zstd could not decompress {source.name}: {done.stderr.strip()}")


def _verified(database: pathlib.Path, commit: str) -> tuple[str, str]:
    """The project the file was built as and its commit, once its one stamp names ``commit`` (any when empty)."""
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                f"SELECT project, head FROM {cbm_index.STAMP_TABLE}").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as failed:
        raise FetchError(f"the downloaded index cannot be read: {failed}") from failed
    if len(rows) != 1 or not rows[0][1] or (commit and rows[0][1] != commit):
        raise FetchError(f"the downloaded index is stamped {rows!r}, not {commit[:12] or 'one commit'} alone")
    return rows[0][0], rows[0][1]


def rename_project(database: pathlib.Path, old: str, new: str, *, qualified: bool) -> None:
    """Move every row of project ``old`` in an index to project ``new``.

    Args:
        database: an index file no reader has open.
        old: the project the rows carry now.
        new: the project they should carry.
        qualified: also rewrite the ``old`` prefix of every qualified name.

    The secondary indexes are dropped first and rebuilt after: updating a keyed
    column under them on 330,000 edges is what costs 9 s.
    """
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("BEGIN")
        indexes = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        ).fetchall()
        for name, _ in indexes:
            connection.execute(f'DROP INDEX "{name}"')
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            key = "project" if "project" in columns else "name" if table == "projects" else ""
            if key:
                connection.execute(
                    f'UPDATE "{table}" SET {key} = ? || substr({key}, ?) '
                    f"WHERE {key} = ? OR {key} LIKE ?", (new, len(old) + 1, old, f"{old}::%"))
            if qualified:
                for column in columns:
                    if column == "qualified_name" or column.endswith("_qn"):
                        connection.execute(
                            f'UPDATE "{table}" SET "{column}" = ? || substr("{column}", ?) '
                            f'WHERE substr("{column}", 1, ?) = ?',
                            (new, len(old) + 1, len(old) + 1, f"{old}."))
        if "store_meta" in tables:
            connection.execute("UPDATE store_meta SET k = replace(k, ?, ?) WHERE k LIKE ?",
                               (f":{old}", f":{new}", f"%:{old}"))
        for _, sql in indexes:
            connection.execute(sql)
        connection.execute("COMMIT")
    finally:
        connection.close()


def _rooted(database: pathlib.Path, project: str, root: pathlib.Path) -> None:
    """Point the project at this checkout, so the tool's text search reads these files."""
    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE projects SET root_path = ? WHERE name = ?", (str(root), project))
        connection.commit()
    finally:
        connection.close()
