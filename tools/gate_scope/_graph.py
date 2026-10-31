"""The first-party import graph, built with the standard library's `ast`.

Why not a third-party import-graph library: those model one dotted name per
module and stop at a namespace directory whose parent is a regular package, so
files go missing from the graph silently, and a file missing from the graph is
silent UNDER-selection, the one direction this module may not fail in. They
also cannot address a directory with a hyphen in its name at all.

Three mechanics the graph has to model:

1. **A file can answer to more than one module name**, when a package is both
   importable from the repository root and installed or put on `sys.path`
   under a shorter name. Names are a set per file, never one canonical name.
2. **Namespace packages.** A directory without `__init__.py` under one that
   has one is a PEP-420 portion. Anything that walks packages by
   `__init__.py` stops there.
3. **Hyphenated directories** (`infra/auto-deploy/tests/`) have no dotted name
   at all and can only ever be addressed as paths.

pytest runs in `prepend` import mode, so a module's name comes from its
basedir: walk up while `__init__.py` exists, and the first directory without
one goes on `sys.path`. Collecting that over every tracked `.py` gives the
sys.path roots this module resolves against.

FAILURE POLICY: this module raises on a broken repo (missing git, unreadable
tree). `select.decide` is the seam that catches and degrades to a full gate;
keeping the raise here means a bug cannot be mistaken for an empty graph.
"""
from __future__ import annotations

import ast
import hashlib
import posixpath
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._classify import is_vendored

#: A dotted name written as a plain string: framework settings such as Django's
#: `INSTALLED_APPS`, `importlib.import_module("...")`, and the module
#: argument of a `python -m ...` subprocess call. Treating these as import
#: edges is the dynamic-import net. It is cheap and it can only widen.
_DOTTED_STRING = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


@dataclass(frozen=True)
class ImportGraph:
    """Files, the module names each answers to, and who imports whom."""

    tracked: tuple[str, ...]
    """Every path `git ls-files` reports, repo-relative, POSIX separators."""

    first_party: tuple[str, ...]
    """Tracked, non-vendored `.py` files."""

    names: dict[str, frozenset[str]]
    """file -> every dotted name that resolves to it."""

    rdeps: dict[str, frozenset[str]]
    """file -> the files that import it."""

    references: dict[str, frozenset[str]]
    """file -> every dotted name it names in an import, resolved or not.

    `rdeps` can only record an edge whose TARGET exists, because the target is
    looked up in an index of files that are in the tree. So a module that has
    been deleted or moved has no importers at all as far as `rdeps` is
    concerned, which reads as "nothing depended on it" when it means "we cannot
    see what did". This map keeps the raw names so the selector can ask the
    question the other way round: who still names the thing that is gone."""

    unparseable: frozenset[str]
    """First-party files `ast` could not parse. A `SyntaxError` means the graph
    is incomplete, and an incomplete graph is not allowed to narrow anything."""

    roots: tuple[str, ...]
    """The discovered sys.path roots, repo-relative ('' is the repo root)."""


def tracked_files(repo: Path) -> tuple[str, ...]:
    """Every tracked path, repo-relative, in POSIX form."""
    done = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(line for line in done.stdout.splitlines() if line)


def sys_path_roots(python_files: tuple[str, ...], repo: Path) -> tuple[str, ...]:
    """The basedir of every file, which is what pytest puts on `sys.path`."""
    roots: set[str] = set()
    for path in python_files:
        roots.add(_basedir(path, repo))
    return tuple(sorted(roots))


def _basedir(path: str, repo: Path) -> str:
    """Walk up from a file while `__init__.py` exists beside it."""
    directory = posixpath.dirname(path)
    while directory and (repo / directory / "__init__.py").exists():
        directory = posixpath.dirname(directory)
    return directory


def module_names(path: str, roots: tuple[str, ...]) -> frozenset[str]:
    """Every dotted name `path` answers to, one per sys.path root it sits in.

    A path segment that is not an identifier (a hyphen, a leading digit) kills
    the name from that root: `auto-deploy/tests/test_gate_scope.py` yields
    nothing except from its own basedir, where the bare name `test_gate_scope`
    is left.
    """
    found: set[str] = set()
    for root in roots:
        if root:
            if not path.startswith(root + "/"):
                continue
            relative = path[len(root) + 1 :]
        else:
            relative = path
        segments = relative.split("/")
        if segments[-1] == "__init__.py":
            segments = segments[:-1]
        else:
            segments[-1] = segments[-1][: -len(".py")]
        if not segments:
            continue
        if all(segment.isidentifier() for segment in segments):
            found.add(".".join(segments))
    return frozenset(found)


def _primary_package(path: str, repo: Path) -> str:
    """The package a relative import inside `path` is resolved against."""
    root = _basedir(path, repo)
    names = module_names(path, (root,))
    if not names:
        return ""
    primary = next(iter(names))
    if posixpath.basename(path) == "__init__.py":
        return primary
    return primary.rpartition(".")[0]


def _referenced_names(tree: ast.AST, package: str) -> set[str]:
    """Every dotted name the source of one file could reach at import time."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _import_from_base(node, package)
            if not base:
                continue
            found.add(base)
            for alias in node.names:
                # An alias is either a submodule or an attribute and the AST
                # cannot tell which. Emit both; over-selection is the safe way
                # to be wrong.
                if alias.name != "*":
                    found.add(f"{base}.{alias.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _DOTTED_STRING.match(node.value):
                found.add(node.value)
    return _with_prefixes(found)


def _import_from_base(node: ast.ImportFrom, package: str) -> str:
    """Resolve the left-hand side of a `from ... import ...` to a dotted name."""
    if not node.level:
        return node.module or ""
    base = package
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    if not base:
        return ""
    return f"{base}.{node.module}" if node.module else base


def _with_prefixes(names: set[str]) -> set[str]:
    """`import a.b.c` executes `a` and `a.b` too, so both are edges."""
    widened: set[str] = set()
    for name in names:
        segments = name.split(".")
        for depth in range(1, len(segments) + 1):
            widened.add(".".join(segments[:depth]))
    return widened


def fingerprint(repo: Path, paths: tuple[str, ...]) -> str:
    """What the parse of `paths` depends on, cheaply enough to ask every time.

    The CONTENT of every file, hashed. Hashing is far cheaper than the parse
    and the floor it guards, so a caller may ask this before every answer.

    Content and not timestamps, though timestamps are cheaper. A stamp of
    `(mtime_ns, size)` cannot be trusted: filesystems quantise modification
    times, so two writes inside one tick share a timestamp, and an edit that
    swaps one character for another keeps the size. Both halves of the stamp
    can then agree about two different trees.

    A file that cannot be read is its own value rather than an error, because
    a vanished file is a different tree and not a reason to stop answering.
    """
    digest = hashlib.blake2b(digest_size=16)
    for path in paths:
        digest.update(path.encode("utf-8"))
        try:
            digest.update((repo / path).read_bytes())
        except OSError:
            digest.update(b"\0missing")
    return digest.hexdigest()


#: Answers already built, keyed on the tree that produced them. Small because
#: one process asks about one tree: the gate calls `decide` once, and the two
#: long-lived callers (the repository index, the diagram tools) walk one
#: checkout. Bounded anyway, so a server that is handed several cannot grow
#: without limit.
_BUILT: dict[tuple[Any, ...], ImportGraph] = {}
_BUILT_MAX = 4


def build(repo: Path, tracked: tuple[str, ...] | None = None) -> ImportGraph:
    """Parse every first-party `.py` once and invert the edges.

    Args:
        repo: the tree to read.
        tracked: its file list, when the caller already has one. The gate never
            passes this and keeps asking git, which is the authority in a
            checkout. The repository index passes it, because it also builds
            from the deploy's `git archive` export, and an export has no git to
            ask.

    The answer is remembered against the tree it was built from, so a caller
    that asks about several changed paths in one process pays the parse once.
    The key is a hash of every first-party file's CONTENT, so a tree that has
    been edited since is a different key and is parsed again; the gate
    selecting against a stale tree is the one failure this package may not
    have. `tests/test_the_graph_is_rebuilt_when_the_tree_moves_under_it.py`
    pins that.
    """
    tracked = tracked_files(repo) if tracked is None else tuple(tracked)
    first_party = tuple(
        path
        for path in tracked
        if path.endswith(".py") and not is_vendored(path)
    )
    key = (str(repo), tracked, fingerprint(repo, first_party))
    remembered = _BUILT.get(key)
    if remembered is not None:
        return remembered
    roots = sys_path_roots(first_party, repo)

    names: dict[str, frozenset[str]] = {}
    name_index: dict[str, set[str]] = {}
    for path in first_party:
        found = module_names(path, roots)
        names[path] = found
        for name in found:
            name_index.setdefault(name, set()).add(path)

    unparseable: set[str] = set()
    rdeps: dict[str, set[str]] = {path: set() for path in first_party}
    references: dict[str, frozenset[str]] = {}
    for path in first_party:
        try:
            source = (repo / path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            unparseable.add(path)
            continue
        package = _primary_package(path, repo)
        referenced = _referenced_names(tree, package)
        references[path] = frozenset(referenced)
        for name in referenced:
            for target in name_index.get(name, ()):
                if target != path:
                    rdeps[target].add(path)

    graph = ImportGraph(
        tracked=tracked,
        first_party=first_party,
        names=names,
        rdeps={path: frozenset(importers) for path, importers in rdeps.items()},
        references=references,
        unparseable=frozenset(unparseable),
        roots=roots,
    )
    if len(_BUILT) >= _BUILT_MAX:
        _BUILT.clear()
    _BUILT[key] = graph
    return graph


def reverse_closure(graph: ImportGraph, seeds: set[str]) -> frozenset[str]:
    """Every file that can reach one of `seeds` through an import chain."""
    reached = {seed for seed in seeds if seed in graph.rdeps}
    frontier = list(reached)
    while frontier:
        current = frontier.pop()
        for importer in graph.rdeps.get(current, frozenset()):
            if importer not in reached:
                reached.add(importer)
                frontier.append(importer)
    return frozenset(reached)
