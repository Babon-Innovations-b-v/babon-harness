"""The always-run floor: tests that read the repo tree instead of importing it.

An import graph cannot see a test that opens a file, walks a directory or
shells out to a binary. Those tests are the ones that catch a stale Caddyfile
or a systemd unit that drifted. A hand-written list of them would rot the day
somebody writes a new one, and it would rot toward running LESS, so the floor
is DERIVED from the test sources on every decision.

A collected test file is on the floor when any of these holds:

  (a) its source mentions a reach token (`__file__`, `rglob`, `os.walk`,
      `iterdir`, `subprocess`, `importlib.import_module`, `__import__`,
      `pkgutil`);
  (b) it contains a string constant that is a tracked path or a tracked
      directory;
  (c) it imports, from first-party code, a module-level name whose assignment
      mentions `__file__`, following re-exports, so a test that reads a file
      through a constant defined elsewhere is still found;
  (d) `ast` cannot parse it, though an unparseable first-party file already
      forces the full gate, so this is belt and braces;
  (e) a `conftest.py` on its directory chain contains a read verb or a repo
      path.

The read-verb restriction in (e) is load-bearing: many conftests use
`Path(__file__)` for nothing but a `sys.path` bootstrap, and counting that as a
reach would put most of the suite on the floor for no reason.

A floor test is then narrowed by its register row: it runs only when one of
its `runs_when` globs matches a changed path.
"""
from __future__ import annotations

import ast
import posixpath
from pathlib import Path

from . import _graph
from ._classify import is_test_file
from ._graph import ImportGraph

#: Rule (a). Any one of these in a test's own source means it can reach
#: outside its imports, so no import graph can bound what it verifies.
REACH_TOKENS = (
    "__file__",
    "rglob",
    "os.walk",
    "iterdir",
    "subprocess",
    "importlib.import_module",
    "__import__",
    "pkgutil",
)

#: Rule (e). A conftest only pulls its tests onto the floor when it actually
#: READS something; `Path(__file__)` for a sys.path bootstrap does not count.
CONFTEST_READ_VERBS = (
    "rglob",
    ".glob(",
    "os.walk",
    "iterdir",
    "subprocess",
    "read_text",
    "read_bytes",
    "open(",
    "yaml.safe_load",
    "json.load(",
)


def collected_test_files(graph: ImportGraph) -> tuple[str, ...]:
    """The first-party files pytest's default patterns would collect."""
    return tuple(path for path in graph.first_party if is_test_file(path))


def repo_path_literals(graph: ImportGraph) -> frozenset[str]:
    """Every tracked path plus every tracked directory, as literal strings."""
    literals: set[str] = set(graph.tracked)
    for path in graph.tracked:
        directory = posixpath.dirname(path)
        while directory:
            literals.add(directory)
            directory = posixpath.dirname(directory)
    return frozenset(literals)


#: Floors already derived, keyed on the tree that produced them, bounded for
#: the same reason `_graph._BUILT` is.
_DERIVED: dict[tuple[object, ...], frozenset[str]] = {}
_DERIVED_MAX = 4


def derive(graph: ImportGraph, repo: Path, conftest_reach: bool = False) -> frozenset[str]:
    """Return the collected test files that read the tree rather than import it.

    `conftest_reach=True` drops the read-verb restriction of rule (e), so a
    test can measure the cost of dropping it; the gate never passes it.

    Remembered against the tree, like `_graph.build`: this is the expensive
    half, because it re-reads every first-party source to look for a path. The key is
    the same content hash, so an edited tree is derived again.
    """
    key = (str(repo), graph.first_party, conftest_reach, _graph.fingerprint(repo, graph.first_party))
    remembered = _DERIVED.get(key)
    if remembered is not None:
        return remembered

    literals = repo_path_literals(graph)
    path_constants = _path_constants(graph, repo)
    sources = _sources(graph, repo)
    conftests = _reaching_conftests(graph, repo, sources, literals, conftest_reach)

    floor: set[str] = set()
    for path in collected_test_files(graph):
        if path in graph.unparseable:
            floor.add(path)
            continue
        source = sources.get(path, "")
        if any(token in source for token in REACH_TOKENS):
            floor.add(path)
        elif _names_a_repo_path(source, literals):
            floor.add(path)
        elif _imports_a_path_constant(source, graph, path_constants):
            floor.add(path)
        elif _inherits_a_reaching_conftest(path, conftests):
            floor.add(path)
    derived = frozenset(floor)
    if len(_DERIVED) >= _DERIVED_MAX:
        _DERIVED.clear()
    _DERIVED[key] = derived
    return derived


def _sources(graph: ImportGraph, repo: Path) -> dict[str, str]:
    """Read every first-party file once; unreadable files come back empty."""
    read: dict[str, str] = {}
    for path in graph.first_party:
        try:
            read[path] = (repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            read[path] = ""
    return read


def _names_a_repo_path(source: str, literals: frozenset[str]) -> bool:
    """Rule (b): a string constant that is a path in this repo."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in literals:
                return True
    return False


def _path_constants(graph: ImportGraph, repo: Path) -> dict[str, frozenset[str]]:
    """Module-level names whose assignment mentions `__file__`, per file.

    Re-exports count. A package `__init__.py` that does
    `from .paths import DEFAULT_METADATA`, imported by a test, would otherwise
    leave that test reachable by no rule at all.
    """
    trees = _parsed(graph, repo)
    return _propagated(_assigned_from_dunder_file(trees), trees, graph)


def _parsed(graph: ImportGraph, repo: Path) -> dict[str, ast.Module]:
    """Every first-party file that parses, as an AST, read and parsed once."""
    trees: dict[str, ast.Module] = {}
    for path in graph.first_party:
        try:
            trees[path] = ast.parse(
                (repo / path).read_text(encoding="utf-8", errors="replace")
            )
        except (OSError, SyntaxError, ValueError):
            continue
    return trees


def _assigned_from_dunder_file(trees: dict[str, ast.Module]) -> dict[str, frozenset[str]]:
    """Module-level names assigned from an expression mentioning `__file__`."""
    found: dict[str, frozenset[str]] = {}
    for path, tree in trees.items():
        names: set[str] = set()
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            value = node.value
            if value is None or "__file__" not in ast.dump(value):
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        if names:
            found[path] = frozenset(names)
    return found


def _propagated(
    seed: dict[str, frozenset[str]], trees: dict[str, ast.Module], graph: ImportGraph
) -> dict[str, frozenset[str]]:
    """Grow the seed by the two hops a real path constant travels.

    A name assigned straight from `__file__` is the seed; from there a path
    constant moves in two ways. A `paths.py` may assign `REPO_ROOT =
    Path(__file__)...` and then `SETTINGS = REPO_ROOT / "settings.yaml"`, and its
    package `__init__.py` may re-export that name, so a test importing it is two
    hops away from anything rule (c) could see.

    Runs to a fixpoint. The sets only grow and the tree is finite, so it
    terminates even on an import cycle.
    """
    carried = dict(seed)
    owners = _module_owners(graph)
    # Both shapes are read once per pass and neither changes between passes:
    # only what is KNOWN about their sources does. Walking the trees inside the
    # loop instead costs millions of `ast.walk` steps per derivation. Hoisted,
    # the pass is a dict lookup and a set intersection, with the same answer.
    imports = _import_edges(trees, owners)
    assignments = _assignment_shapes(trees)
    while True:
        grew = False
        for path in trees:
            known = set(carried.get(path, ()))
            known |= _borrowed_names(imports.get(path, ()), carried)
            known |= _derived_names(assignments.get(path, ()), known)
            if known and known != set(carried.get(path, ())):
                carried[path] = frozenset(known)
                grew = True
        if not grew:
            return carried


def _import_edges(
    trees: dict[str, ast.Module], owners: dict[str, frozenset[str]]
) -> dict[str, tuple[tuple[frozenset[str], tuple[tuple[str, str], ...]], ...]]:
    """Every `from X import ...` per file, resolved to its candidate sources once.

    Each edge is the files the import could be reading from, paired with the
    `(imported name, bound name)` of every alias on it. An import whose source
    resolves to nothing first-party is dropped here rather than on every pass.
    """
    edges: dict[str, tuple[tuple[frozenset[str], tuple[tuple[str, str], ...]], ...]] = {}
    for path, tree in trees.items():
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            sources = _import_sources(path, node, owners)
            if not sources:
                continue
            found.append(
                (
                    sources,
                    tuple((alias.name, alias.asname or alias.name) for alias in node.names),
                )
            )
        if found:
            edges[path] = tuple(found)
    return edges


def _assignment_shapes(
    trees: dict[str, ast.Module]
) -> dict[str, tuple[tuple[frozenset[str], frozenset[str]], ...]]:
    """Every module-level assignment as the names it mentions and the ones it binds.

    An assignment binding no plain name can never carry a path constant forward,
    so it is dropped here instead of being re-walked on every pass.
    """
    shapes: dict[str, tuple[tuple[frozenset[str], frozenset[str]], ...]] = {}
    for path, tree in trees.items():
        found = []
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            if node.value is None:
                continue
            bound = frozenset(
                target.id for target in targets if isinstance(target, ast.Name)
            )
            if not bound:
                continue
            mentioned = frozenset(
                inner.id for inner in ast.walk(node.value) if isinstance(inner, ast.Name)
            )
            found.append((mentioned, bound))
        if found:
            shapes[path] = tuple(found)
    return shapes


def _borrowed_names(
    edges: tuple[tuple[frozenset[str], tuple[tuple[str, str], ...]], ...],
    carried: dict[str, frozenset[str]],
) -> set[str]:
    """The path constants this file imports out of another first-party file."""
    borrowed: set[str] = set()
    for sources, aliases in edges:
        for source in sources:
            constants = carried.get(source, frozenset())
            if not constants:
                continue
            borrowed |= {bound for name, bound in aliases if name in constants}
    return borrowed


def _derived_names(
    assignments: tuple[tuple[frozenset[str], frozenset[str]], ...], known: set[str]
) -> set[str]:
    """Module-level names assigned from an expression naming a known constant."""
    derived: set[str] = set()
    for mentioned, bound in assignments:
        if mentioned & known:
            derived |= bound
    return derived


def _module_owners(graph: ImportGraph) -> dict[str, frozenset[str]]:
    """Dotted module name -> the first-party files it can resolve to."""
    owners: dict[str, set[str]] = {}
    for path, module_names in graph.names.items():
        for module_name in module_names:
            owners.setdefault(module_name, set()).add(path)
    return {name: frozenset(paths) for name, paths in owners.items()}


def _import_sources(
    path: str, node: ast.ImportFrom, owners: dict[str, frozenset[str]]
) -> frozenset[str]:
    """The first-party files one `from X import ...` can be reading from."""
    if not node.level:
        return owners.get(node.module or "", frozenset())
    directory = posixpath.dirname(path)
    for _ in range(node.level - 1):
        directory = posixpath.dirname(directory)
    parts = (node.module or "").split(".") if node.module else []
    base = posixpath.join(directory, *parts) if parts else directory
    return frozenset({f"{base}.py", f"{base}/__init__.py"})


def _imports_a_path_constant(
    source: str, graph: ImportGraph, path_constants: dict[str, frozenset[str]]
) -> bool:
    """Rule (c): the test borrows a path someone else computed from `__file__`."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return True
    name_index: dict[str, set[str]] = {}
    for owner in path_constants:
        for module_name in graph.names.get(owner, frozenset()):
            name_index.setdefault(module_name, set()).add(owner)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        for owner in name_index.get(node.module, ()):
            borrowed = path_constants[owner]
            if any(alias.name in borrowed for alias in node.names):
                return True
    return False


def _reaching_conftests(
    graph: ImportGraph,
    repo: Path,
    sources: dict[str, str],
    literals: frozenset[str],
    conftest_reach: bool,
) -> frozenset[str]:
    """The directories whose `conftest.py` reads the tree."""
    reaching: set[str] = set()
    for path in graph.first_party:
        if posixpath.basename(path) != "conftest.py":
            continue
        source = sources.get(path, "")
        if conftest_reach:
            reaches = any(token in source for token in REACH_TOKENS)
        else:
            reaches = any(verb in source for verb in CONFTEST_READ_VERBS)
        if reaches or _names_a_repo_path(source, literals):
            reaching.add(posixpath.dirname(path))
    return frozenset(reaching)


def _inherits_a_reaching_conftest(path: str, conftests: frozenset[str]) -> bool:
    """Rule (e): a reaching `conftest.py` sits on this test's directory chain."""
    directory = posixpath.dirname(path)
    while True:
        if directory in conftests:
            return True
        if not directory:
            return False
        directory = posixpath.dirname(directory)
