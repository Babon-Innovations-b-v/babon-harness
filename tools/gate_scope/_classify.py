"""What a single changed path means for the gate's scope.

One rule governs this file: a path we do not recognise is not evidence of
safety. It returns `FULL_FORCING`, the whole suite runs, and the deploy is
slower than it needed to be. The opposite mistake ships a regression through a
gate that reported green, and it is silent.

The "recognised inert" list below therefore means one narrow thing: *this
path contributes no reverse-import closure of its own*. It does NOT mean "no
test covers this file". Coverage for these paths comes from the floor and the
register's `runs_when` triggers: a `.sh` change still runs the deploy tests
that read it.

`.claude/` follows the same document rules as `.claude/scripts/gate-scope.py`,
the shared pre-push default: the harness's own code there (hooks, scripts, the
index, the settings that wire them) is code, and everything else under
`.claude/` (skills, notes, the soul) is a document.
"""
from __future__ import annotations

import posixpath

FULL_FORCING = "full-forcing"
INERT = "inert"
PYTHON = "python"

#: Paths whose vendored code is excluded from the import graph, so nothing can
#: be said about who depends on them. Excluded from the graph means unknown,
#: and unknown means full. Empty until this repository vendors something.
VENDORED_PREFIXES: tuple[str, ...] = ()

#: Changing what the tests run *inside* is never in scope for narrowing: a new
#: pin moves every import in the tree.
_ENVIRONMENT_SUFFIXES = (".lock", ".toml", ".cfg", ".ini")

#: The selector's own tree and the gate step that consume its decision are
#: narrowed like anything else: neither is importable by product code, so a
#: change there can only break the tests that read them, and those are named
#: by register rows. What a bad table can do is make a FUTURE commit's
#: selection too narrow, and the nightly unselected audit is what catches that.
#: Kept as a named, empty seam so putting a forced-full rule back is one entry.
_SELF_PREFIXES: tuple[str, ...] = ()
_SELF_PATHS: tuple[str, ...] = ()

#: Recognised-inert file extensions. Read the module docstring before adding
#: one: the question is not "is this file harmless", it is "can this file be
#: the tail of an import chain".
_INERT_SUFFIXES = (
    ".md",
    ".astro",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".woff2",
    ".ico",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".sql",
    ".txt",
    ".sh",
    ".service",
    ".timer",
    ".xml",
    ".properties",
    ".gitignore",
    ".gitkeep",
    ".gitattributes",
    # Read by `docker build` and by nothing in pytest. What checks it is the
    # build itself: the verifying run builds its own commit's images.
    ".dockerignore",
)

#: Recognised-inert exact basenames.
_INERT_BASENAMES = (
    "Caddyfile",
    "LICENSE",
    "LICENCE",
    # An ignore list is a tool's input, never the tail of an import chain: no
    # `import` statement can name one.
    ".cbmignore",
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
)

#: Recognised-inert basename prefixes.
_INERT_BASENAME_PREFIXES = ("Dockerfile",)

#: Whole trees that carry no import edge into the test suite: documents and
#: working notes. Inert is about the IMPORT graph, not coverage: a test that
#: reads `business/` or `docs/` still runs through its register row.
_INERT_PREFIXES = ("business/", "docs/", ".github/ISSUE_TEMPLATE/")

#: The harness's own code under `.claude/`, exactly the prefixes
#: `.claude/scripts/gate-scope.py` calls code. A `.py` there is classified like
#: any other `.py`; anything else there (a hook script with no extension, the
#: settings file) can change what every session runs and forces the full gate.
_CLAUDE_CODE_PREFIXES = (
    ".claude/hooks/",
    ".claude/scripts/",
    ".claude/index/",
    ".claude/settings.json",
)


def _classify_claude(path: str) -> str:
    """`.claude/`: code where gate-scope.py says code, a document elsewhere."""
    if path.endswith(".md"):
        return INERT
    if path.startswith(_CLAUDE_CODE_PREFIXES):
        return PYTHON if path.endswith(".py") else FULL_FORCING
    return INERT


def classify(path: str) -> str:
    """Return `FULL_FORCING`, `PYTHON` or `INERT` for one repo-relative path."""
    if not path:
        return FULL_FORCING
    basename = posixpath.basename(path)
    if path.endswith(_ENVIRONMENT_SUFFIXES) or basename == "pyproject.toml":
        return FULL_FORCING
    if path.startswith(_SELF_PREFIXES) or path in _SELF_PATHS:
        return FULL_FORCING
    if VENDORED_PREFIXES and path.startswith(VENDORED_PREFIXES):
        return FULL_FORCING
    if path.startswith(".claude/"):
        return _classify_claude(path)
    if path.endswith(".py"):
        return PYTHON
    if path.endswith(_INERT_SUFFIXES):
        return INERT
    if basename in _INERT_BASENAMES:
        return INERT
    if basename.startswith(_INERT_BASENAME_PREFIXES):
        return INERT
    if path.startswith(_INERT_PREFIXES):
        return INERT
    return FULL_FORCING


def is_vendored(path: str) -> bool:
    """True for a tree we do not parse, so cannot reason about."""
    return bool(VENDORED_PREFIXES) and path.startswith(VENDORED_PREFIXES)


def is_test_file(path: str) -> bool:
    """True when pytest's default `python_files` patterns would collect it.

    The defaults (`test_*.py`, `*_test.py`) are what the gate runs under; a
    `[tool.pytest]` section that changes `python_files` must change this too.
    """
    basename = posixpath.basename(path)
    if not basename.endswith(".py"):
        return False
    return basename.startswith("test_") or basename.endswith("_test.py")
