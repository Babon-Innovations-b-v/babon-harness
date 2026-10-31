#!/usr/bin/env python3
"""Git pre-commit guard: a commit may not need what it leaves behind.

When several sessions share one checkout, a commit tears easily: a test is
committed while the file it reads stays in the working tree, so the suite is
green on the box that wrote it and red on every other box. Writing "commit the
file too" down does not hold, so this is the mechanical check instead.

WHAT IT BLOCKS, first rule. A commit is refused when a STAGED FILE names a repo
path that this commit leaves behind: a path that is untracked, or one that is
modified in the working tree and not staged. Four match rules, narrowest first:

  full-path    the staged file carries the left-behind path itself, whole or as
               a trailing fragment (``tests/test_example_case.py``);
  basename     it carries a basename that resolves to exactly one file in the
               repo, is long enough to be a name rather than a word, and is not
               on AMBIGUOUS_BASENAMES (``__init__.py`` and friends);
  import-stem  on a ``from``/``import`` line only, it names a module stem that
               resolves to exactly one ``.py`` file in the repo;
  shell-name   it names a shell function or CAPS variable that the working-tree
               copy of a left-behind ``.sh`` file defines and the committed copy
               does not (the ``SOME_NAME: unbound variable`` shape).

A left-behind path that is UNTRACKED blocks on any of the four rules: nobody
else has that file, so the commit is torn for certain. A left-behind path that
is merely dirty still resolves on every other checkout, so it blocks only on
``shell-name``, which is symbol-level evidence and needs no path to resolve;
the three path-shaped rules print a note and let the commit through. That split
is what makes the guard survivable in a checkout several sessions share, where
most of the dirt belongs to somebody else. ``blocks()`` carries the full
argument.

SCOPE. Every staged file is read, not only the staged tests: a step file
needing its sibling, a page needing its stylesheet and a doc row needing its
script tear a commit just as surely as a test needing its fixture. The whole
cost is the staged set plus the dirty set; nothing walks the repo, and the two
index listings behind the uniqueness tests are built at most once and only
when a rule actually asks.

The same staged blobs are checked for merge conflict markers, which costs
nothing extra because they are already read.

WHAT IT BLOCKS, second rule. A repository may list, under ``sourced_shell_dirs``
in ``.claude/project.json``, directories whose ``*.sh`` files are sourced in
order into ONE shell with ``set -u``, so a name one file reads and another
assigns is a contract between files rather than a coincidence. A staged file
there that reads a name nothing in the directory assigns is refused, comparing
against the directory as it WILL BE after this commit: staged content where a
file is staged, committed content everywhere else. The first rule cannot see
this tear: the consumer names no path, and the producer is a tracked file
carrying unstaged edits, which the first rule treats as a note. A read that
carries its own default (``${name:-}``) is safe under ``set -u`` and is not
counted.

FAILURE POLICY. A finding is RED: the check ran, the answer is no, exit 1, the
commit is blocked. An inability to run is AMBER: exit 0, the commit is allowed,
one line on stderr naming what could not be read. Amber never escalates here,
because escalation would wedge the tree.

ENV. ``TORN_GUARD=0`` disarms it. ``TORN_GUARD_MAX_BYTES`` (default 262144) is
the staged blob size above which a file is skipped as amber.
``TORN_GUARD_MAX_DIRTY`` (default 400) is the dirty-set size above which the
guard allows and says so: a tree that large is in a state it cannot reason
about.
"""

import json
import os
import pathlib
import posixpath
import re
import subprocess
import sys

MAX_BYTES = int(os.environ.get("TORN_GUARD_MAX_BYTES") or 262144)
MAX_DIRTY = int(os.environ.get("TORN_GUARD_MAX_DIRTY") or 400)

_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "project.json"

#: Rule 4 reads two copies of each left-behind shell file. Past this many, the
#: rule is skipped (amber) rather than turning a commit into a git storm.
MAX_SHELL_SCAN = 50

#: Pairs printed before the message is trimmed. A wall of output is read as
#: noise, and the fix is the same for the first pair as for the fiftieth.
MAX_REPORTED = 20

#: Basenames that name a role, not a file. Each tends to exist many times in a
#: repository, so a staged file mentioning one says nothing about which.
AMBIGUOUS_BASENAMES = frozenset({
    "__init__.py", "conftest.py", "CLAUDE.md", "README.md", "index.html",
    "index.ts", "index.tsx", "package.json", "package-lock.json",
    "tsconfig.json", "pyproject.toml", "Dockerfile", "types.ts", "utils.py",
    "main.py", "app.py", "config.py", "settings.py", "__main__.py",
    ".gitignore", "Caddyfile",
})

#: Shell names that describe a role, not a file. A script defining one of these
#: says nothing about which script it is, so a staged file mentioning the same
#: token is not evidence that the two belong together. Subtracting the tracked
#: shell vocabulary removes most of these on its own, but not in a young repo or
#: a fresh worktree where there is little vocabulary to subtract, and the rule
#: has to be right in both.
AMBIGUOUS_SHELL_NAMES = frozenset({
    "REPO", "REPO_ROOT", "ROOT", "ROOT_DIR", "BASE", "BASE_DIR", "SCRIPT_DIR",
    "DIR", "WORK", "WORK_DIR", "WORKDIR", "TMP", "TMPDIR", "TMP_DIR", "OUT",
    "OUT_DIR", "SRC", "DEST", "TARGET", "FILE", "PATH", "NAME", "LOG",
    "LOG_DIR", "LOG_FILE", "STATE_DIR", "IMAGE", "TAG", "SHA", "REGISTRY",
    "HOST", "PORT", "URL", "ENV", "TIMEOUT", "RETRIES", "VERBOSE", "DEBUG",
    "usage", "main", "log", "die", "run", "cleanup", "setup", "check",
})

#: Import stems that are words before they are modules.
AMBIGUOUS_STEMS = frozenset({
    "utils", "config", "types", "index", "main", "models", "views", "tests",
    "common", "helpers", "constants", "client", "server", "core", "paths",
    "state",
})

_CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7})(\s|$)")

_TOKEN = re.compile(r"[A-Za-z0-9_./+-]+")
_IMPORT_LINE = re.compile(r"^\s*(from|import)\b")
_SHELL_FUNCTION = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", re.M)
_SHELL_CAPS_VAR = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})=", re.M)

_AMBER = []


def amber(reason):
    """Record one thing the guard could not read. Never blocks."""
    _AMBER.append(reason)


def git(args):
    """Run git and return (returncode, stdout). Never raises."""
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, errors="replace"
        )
    except OSError as error:
        amber(f"git could not run ({error})")
        return 1, ""
    return done.returncode, done.stdout


def git_bytes(args):
    """Run git and return (returncode, stdout as bytes). Never raises."""
    try:
        done = subprocess.run(["git", *args], capture_output=True)
    except OSError as error:
        amber(f"git could not run ({error})")
        return 1, b""
    return done.returncode, done.stdout


def in_a_repo():
    """True when the current directory is inside a git working tree."""
    code, out = git(["rev-parse", "--is-inside-work-tree"])
    return code == 0 and out.strip() == "true"


def _zero_separated(args):
    """The NUL-separated path list a git plumbing command printed."""
    code, out = git(args)
    if code != 0:
        return None
    return [path for path in out.split("\0") if path]


def staged_paths():
    """Repo-relative paths this commit would add, copy, modify or rename."""
    return _zero_separated(
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    )


def dirty_paths(staged):
    """Repo-relative paths this commit would leave behind.

    Worktree-modified-but-not-staged plus untracked-and-not-ignored, minus
    anything that is staged: a path going into the commit is not left behind,
    even when it also carries further unstaged edits.
    """
    modified = _zero_separated(["diff", "--name-only", "-z"])
    untracked = _zero_separated(["ls-files", "-z", "--others", "--exclude-standard"])
    if modified is None or untracked is None:
        return None
    staged_set = set(staged)
    return sorted({path for path in modified + untracked if path not in staged_set})


def never_committed(staged):
    """The left-behind paths git has never seen: untracked, and not staged now.

    This is the line between blocking and warning. A path that has never been
    committed does not exist for anybody else, so a staged file that needs it is
    torn for certain. A path that IS tracked and merely carries unstaged edits
    still resolves on every other checkout, so the same reference is at worst
    stale, and blocking on it would mean any other session's dirty file could
    stop your commit. In a checkout several sessions share, a guard that blocks
    on other people's dirt is a guard that gets disarmed within a day, and then
    it protects nothing.
    """
    untracked = _zero_separated(["ls-files", "-z", "--others", "--exclude-standard"])
    if untracked is None:
        return None
    staged_set = set(staged)
    return {path for path in untracked if path not in staged_set}


def is_test_path(path):
    """True for a file pytest would collect as a test, or that lives in a tests dir."""
    name = posixpath.basename(path)
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return "/tests/" in path or path.startswith("tests/")


def staged_blob(path):
    """The staged content of `path` as text, or None when it cannot be read."""
    code, raw = git_bytes(["show", f":{path}"])
    if code != 0:
        amber(f"could not read the staged copy of {path}")
        return None
    if len(raw) > MAX_BYTES:
        amber(f"{path} is larger than {MAX_BYTES} bytes; not scanned")
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        amber(f"{path} is not UTF-8 text; not scanned")
        return None


def working_tree_text(path):
    """The working-tree content of `path` as text, or "" when unreadable."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        amber(f"could not read {path} from the working tree")
        return ""
    if len(raw) > MAX_BYTES:
        amber(f"{path} is larger than {MAX_BYTES} bytes; not scanned")
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def committed_text(path):
    """The content `path` has in the index, or in HEAD, or "" when it has neither."""
    for revision in (f":{path}", f"HEAD:{path}"):
        code, raw = git_bytes(["show", revision])
        if code == 0 and len(raw) <= MAX_BYTES:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return ""
    return ""


class RepoIndex:
    """Every path the repo holds right now, answered by basename and by stem.

    Built at most once per run, and only when a basename or import-stem rule
    actually needs to know whether a name is unique. Two git calls, no walk.
    """

    def __init__(self):
        self._by_basename = None
        self._by_stem = None

    def _build(self):
        tracked = _zero_separated(["ls-files", "-z"]) or []
        untracked = _zero_separated(
            ["ls-files", "-z", "--others", "--exclude-standard"]
        ) or []
        by_basename = {}
        by_stem = {}
        for path in tracked + untracked:
            name = posixpath.basename(path)
            by_basename.setdefault(name, set()).add(path)
            if name.endswith(".py"):
                by_stem.setdefault(name[:-3], set()).add(path)
        self._by_basename = by_basename
        self._by_stem = by_stem

    def basename_is_unique(self, name):
        if self._by_basename is None:
            self._build()
        return len(self._by_basename.get(name, ())) == 1

    def stem_is_unique(self, stem):
        if self._by_stem is None:
            self._build()
        return len(self._by_stem.get(stem, ())) == 1


def tokens_in(text):
    """Every whole token in `text`, path-like tokens kept whole."""
    return {match.group(0) for match in _TOKEN.finditer(text)}


def names_in(text):
    """Every token plus every path tail of it, so both path rules are set lookups.

    A test rarely writes the repo-relative path in full; it writes the tail it
    cares about ("tests/test_example_case.py"). Expanding each token into its
    tails once, rather than scanning the whole token set per left-behind path,
    keeps the guard flat in the size of the dirty set.
    """
    names = set()
    for token in tokens_in(text):
        names.add(token)
        tail = token
        while "/" in tail:
            tail = tail.split("/", 1)[1]
            names.add(tail)
    return names


def import_tokens_in(text):
    """The name parts appearing on `from ...` / `import ...` lines only."""
    parts = set()
    for line in text.splitlines():
        if not _IMPORT_LINE.match(line):
            continue
        for token in _TOKEN.finditer(line):
            parts.update(piece for piece in re.split(r"[./]", token.group(0)) if piece)
    return parts


def shell_names(text):
    """Function names and CAPS variables this shell source defines."""
    return set(_SHELL_FUNCTION.findall(text)) | set(_SHELL_CAPS_VAR.findall(text))


def new_shell_names(path):
    """Shell names the working-tree copy of `path` defines and the commit does not."""
    return shell_names(working_tree_text(path)) - shell_names(committed_text(path))


def path_is_named(names, dirty_path):
    """True when the staged text carries the left-behind path, whole or as a tail.

    A path whose whole name is digits is refused before the lookup, because it
    is not evidence of anything. Every shell script writes `$1`, `${1:-}` and
    `awk '{print $2}'`, so a stray file named `1` at the repo root (a `2>1`
    typo makes one) would otherwise make half the scripts in the tree name it.

    Narrow on purpose. `Makefile`, `Dockerfile` and `LICENSE` are real
    extensionless paths a staged file can legitimately name, so the rule is not
    widened to "no extension"; only an all-digit name, which nothing in this
    tree is, is dropped.
    """
    if dirty_path.isdigit():
        return False
    return dirty_path in names


def basename_is_named(names, dirty_path, index):
    """The unique, long-enough basename of `dirty_path` if the staged text names it."""
    name = posixpath.basename(dirty_path)
    if name in AMBIGUOUS_BASENAMES:
        return None
    long_enough = (len(name) >= 5 and "." in name) or len(name) >= 8
    if not long_enough or name not in names:
        return None
    return name if index.basename_is_unique(name) else None


def stem_is_named(import_parts, dirty_path, index):
    """The unique import stem of a left-behind `.py` file if an import line names it."""
    if not dirty_path.endswith(".py"):
        return None
    stem = posixpath.basename(dirty_path)[:-3]
    if len(stem) < 5 or stem in AMBIGUOUS_STEMS or stem not in import_parts:
        return None
    return stem if index.stem_is_unique(stem) else None


def shell_vocabulary_of_the_repo():
    """Every function and CAPS variable name the tracked shell files already use.

    A name only counts as evidence that a staged file needs a left-behind script
    if that script is where the name comes from. Without this subtraction, a
    brand-new script contributes EVERY name it defines, including the generic
    ones, because an untracked file has no committed copy to diff against, so
    `new_shell_names` returns all of them.

    Without it, a new test defining `REPO_ROOT = Path(...)` in Python is tied to
    an unrelated untracked shell script that happens to define `REPO_ROOT=` too.
    A generic name is defined in many tracked shell files, so subtracting the
    tracked vocabulary removes it, while a genuinely new name survives.
    """
    tracked = _zero_separated(["ls-files", "-z", "--", "*.sh"])
    if tracked is None:
        amber("could not list the tracked shell files; shell names stay ambiguous")
        return None
    names = set()
    for path in tracked:
        text = committed_text(path)
        if text:
            names |= shell_names(text)
    return names


def left_behind_shell_names(dirty):
    """Per left-behind `.sh` path, the shell names ONLY that file introduces.

    Read once per path, not once per staged file, and capped: past
    MAX_SHELL_SCAN files the rule is skipped as amber rather than turning one
    commit into hundreds of git calls.
    """
    scripts = [path for path in dirty if path.endswith(".sh")]
    if not scripts:
        # Nothing to compare against, so the tracked shell vocabulary below
        # is not read at all. Most commits land here.
        return {}
    if len(scripts) > MAX_SHELL_SCAN:
        amber(f"{len(scripts)} uncommitted shell files; the shell-name rule is skipped")
        return {}
    already_used = shell_vocabulary_of_the_repo()
    if already_used is None:
        return {}
    generic = already_used | AMBIGUOUS_SHELL_NAMES
    return {path: new_shell_names(path) - generic for path in scripts}


def shell_name_is_named(names, dirty_path, shell_names_by_path):
    """A shell name defined only in the left-behind copy of `dirty_path`, if named."""
    for name in sorted(shell_names_by_path.get(dirty_path, ())):
        if name in names:
            return name
    return None


def sourced_shell_dirs():
    """The directories whose files are sourced into a single shell with `set -u`
    on, from `.claude/project.json` (`sourced_shell_dirs`); none when unset."""
    try:
        listed = json.loads(_CONFIG_PATH.read_text()).get("sourced_shell_dirs") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [str(entry).rstrip("/") + "/" for entry in listed]


#: Names the orchestrator, the environment or bash itself provides, so a read
#: with no assignment among the step files is not evidence of a tear.
SHELL_PROVIDED = frozenset({
    "HOME", "PATH", "PWD", "USER", "SHELL", "TERM", "LANG", "LC_ALL", "TMPDIR",
    "IFS", "PIPESTATUS", "BASH_SOURCE", "FUNCNAME", "LINENO", "RANDOM",
    "SECONDS", "HOSTNAME", "UID", "EUID", "OLDPWD", "REPLY",
})

#: Anchored on a word boundary rather than line start, because plenty of real
#: bindings are not the first thing on their line: `if name=$(...)` and
#: `while IFS= read -r name` are both common.
_SHELL_ASSIGN = re.compile(r"(?:^|[\s;&|(])([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\+=)", re.M)
_SHELL_LOOP_VAR = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", re.M)
#: `local`, `declare`, `export`, `readonly` and `read` all BIND a list of names,
#: with or without a value each. `local http_code` binds it just as surely as
#: `http_code=`, and `local a b c` binds three. Missing that turns the whole
#: check into noise.
_SHELL_DECLARE_LINE = re.compile(
    r"(?:^|[\s;&|(])(?:local|declare|typeset|export|readonly|read)\b([^\n;&|]*)", re.M
)
_SHELL_NAME_IN_LIST = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)(?==|\s|$)")
#: A read that carries its own default (`${x:-}`) is safe under `set -u`, so the
#: capture deliberately stops at the first character that is not a name.
_SHELL_PLAIN_READ = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)[}\s\"'/:,)\]]")


def shell_assigns(text):
    """Every name this shell source binds, by assignment, declaration or loop."""
    names = set(_SHELL_ASSIGN.findall(text)) | set(_SHELL_LOOP_VAR.findall(text))
    for declared in _SHELL_DECLARE_LINE.findall(text):
        for name in _SHELL_NAME_IN_LIST.findall(declared):
            names.add(name)
    return names


def shell_plain_reads(text):
    """Names read WITHOUT a `${x:-default}`, which `set -u` makes fatal."""
    names = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name in _SHELL_PLAIN_READ.findall(line):
            names.add(name)
    defaulted = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):[-=?+]", text))
    return names - defaulted


def sourced_shell_contract_breaks(staged, blobs):
    """Names a staged sourced file reads that NOTHING in its directory assigns.

    The files of a sourced directory run in order in one shell with `set -u`, so
    a name read in one file and assigned in another is a contract between them,
    and committing one side without the other kills the run at that line rather
    than failing a test. The path rules cannot see it: the consumer names no
    path, and the producer is a tracked file that merely carries unstaged edits,
    which `blocks()` deliberately treats as a note.

    What is compared: names the staged files read plainly, against names
    assigned anywhere in their directory as it WILL BE after this commit, which
    is the staged content where a file is staged and the committed content
    everywhere else. That is the shape the shell will actually source.
    """
    broken = []
    for directory in sourced_shell_dirs():
        broken += _contract_breaks_in(directory, staged, blobs)
    return broken


def _contract_breaks_in(directory, staged, blobs):
    """The (path, name) pairs one sourced directory's staged files break."""
    staged_steps = {
        path: blobs.get(path)
        for path in staged
        if path.startswith(directory) and path.endswith(".sh")
    }
    staged_steps = {path: text for path, text in staged_steps.items() if text}
    if not staged_steps:
        return []

    tracked = _zero_separated(["ls-files", "-z", "--", f"{directory}*.sh"])
    if tracked is None:
        amber(f"could not list the files of {directory}; the sourced-shell contract is unchecked")
        return []

    assigned = set()
    for path in set(tracked) | set(staged_steps):
        text = staged_steps.get(path)
        if text is None:
            text = committed_text(path)
        if text:
            assigned |= shell_assigns(text)

    broken = []
    for path, text in sorted(staged_steps.items()):
        for name in sorted(shell_plain_reads(text)):
            if name in assigned or name in SHELL_PROVIDED or name.isdigit():
                continue
            broken.append((path, name))
    return broken


def contract_report(broken):
    """The block message for a step file reading a name the cycle will not have."""
    lines = [
        "BLOCKED: this commit stages a sourced shell file that reads a name nothing assigns.",
        "",
        "Its directory is sourced into ONE shell with `set -u`, so this does not",
        "fail a test, it kills the run at that line.",
        "",
        "  staged file  ->  name it reads with no producer",
    ]
    for path, name in broken[:MAX_REPORTED]:
        lines.append(f"  {path}  ->  ${name}")
    if len(broken) > MAX_REPORTED:
        lines.append(f"  ... and {len(broken) - MAX_REPORTED} more")
    lines += [
        "",
        "Either stage the file that assigns it, or give the read a default",
        "(`${name:-}`), which is what makes it safe under `set -u`.",
    ]
    return "\n".join(lines)


def findings(blobs, dirty, index):
    """Every (staged file, left-behind path, token, rule) pair this commit tears.

    Reads every staged file, not only the tests. The net is wide on purpose,
    and what keeps it survivable is `blocks()` rather than a narrow scope: only
    a path git has never seen, or a shell symbol that exists solely in an
    uncommitted copy, actually stops a commit. Everything else prints a note,
    so the ordinary commits people make all day pass untouched.
    """
    found = []
    shell_names_by_path = left_behind_shell_names(dirty)
    for staged_test, blob in sorted(blobs.items()):
        if blob is None:
            continue
        names = names_in(blob)
        import_parts = import_tokens_in(blob)
        for dirty_path in dirty:
            if path_is_named(names, dirty_path):
                found.append((staged_test, dirty_path, dirty_path, "full-path"))
                continue
            name = basename_is_named(names, dirty_path, index)
            if name:
                found.append((staged_test, dirty_path, name, "basename"))
                continue
            stem = stem_is_named(import_parts, dirty_path, index)
            if stem:
                found.append((staged_test, dirty_path, stem, "import-stem"))
                continue
            shell_name = shell_name_is_named(names, dirty_path, shell_names_by_path)
            if shell_name:
                found.append((staged_test, dirty_path, shell_name, "shell-name"))
    return found


def report(found):
    """The block message: the offending pairs, then the one move that fixes it."""
    lines = [
        "BLOCKED: this commit stages files that need something it leaves behind.",
        "Either the path below has never been committed, or the symbol named is",
        "defined only in an uncommitted copy. Committed as-is, this is green here",
        "and broken on every other checkout.",
        "",
        "  staged file  ->  path left behind  (matched, rule)",
    ]
    for staged_test, dirty_path, token, rule in found[:MAX_REPORTED]:
        lines.append(f"  {staged_test}  ->  {dirty_path}  ({token}, {rule})")
    if len(found) > MAX_REPORTED:
        lines.append(f"  ... and {len(found) - MAX_REPORTED} more pairs")
    left_behind = sorted({dirty_path for _, dirty_path, _, _ in found})
    lines += [
        "",
        "Fix it in one move, either:",
        "  git add " + " ".join(left_behind),
        "  git stash push -- " + " ".join(left_behind),
        "",
        "The override is still there: `git commit --no-verify` commits anyway, and",
        "so does TORN_GUARD=0. Both belong to a human at a terminal who can",
        "see what they are waiving; a session reaching for either is blocked by",
        ".claude/hooks/commit_guard.py. A false block is a bug in the rule and",
        "should be fixed where the rule lives, not routed around.",
    ]
    return "\n".join(lines)


def warn(found):
    """The non-blocking note: references to files that are tracked but dirty.

    Worth saying, never worth stopping a commit for. The referenced file exists
    on main, so nothing is torn; what it may be is stale, and in a shared
    checkout the dirt usually belongs to somebody else entirely.
    """
    lines = [
        "note: this commit names paths that carry unstaged edits. Nothing is torn,",
        "they are all tracked, but what you commit may not match what you tested:",
        "",
    ]
    for staged_test, dirty_path, token, rule in found[:MAX_REPORTED]:
        lines.append(f"  {staged_test}  ->  {dirty_path}  ({token}, {rule})")
    if len(found) > MAX_REPORTED:
        lines.append(f"  ... and {len(found) - MAX_REPORTED} more")
    return "\n".join(lines)


def blocks(finding, never_seen):
    """True when this finding is proof of a tear rather than a note about staleness.

    Two kinds of evidence, and only one of them justifies stopping a commit.

    The `shell-name` rule is symbol-level: it fires only on a name that the
    working-tree copy of a file defines and the COMMITTED copy does not. That is
    proof on its own, whether or not the file is tracked, because the symbol
    does not exist for anybody else no matter what the path resolves to. A
    script calling a function whose definition sits uncommitted in a TRACKED,
    merely-dirty sibling dies on `unbound variable` everywhere else; requiring
    the path to be untracked would miss exactly that.

    The path-shaped rules (`full-path`, `basename`, `import-stem`) are weaker:
    they say a staged file mentions a path. If that path is tracked, it resolves
    on every checkout and nothing is torn; the mention is at worst stale. In a
    checkout several sessions share, blocking there means any colleague's unstaged
    edit can stop your commit, which is how a guard gets disarmed and stops
    protecting anything.
    """
    _, dirty_path, _, rule = finding
    if rule == "shell-name":
        return True
    return dirty_path in never_seen


def staged_files_with_conflict_markers(blobs):
    """Staged paths whose staged content still carries merge conflict markers.

    Free, because the blobs are already read for the rules above, and worth
    having: a `git stash pop` can leave `<<<<<<< Updated upstream` inside a
    tracked file with no merge in progress, so nothing in git's own state says
    anything is wrong.
    """
    marked = []
    for path, blob in sorted(blobs.items()):
        if blob is None:
            continue
        for line in blob.splitlines():
            if _CONFLICT_MARKER.match(line):
                marked.append(path)
                break
    return marked


def conflict_report(conflicted):
    """The block message for staged conflict markers."""
    lines = [
        "BLOCKED: this commit stages files that still contain conflict markers.",
        "",
    ]
    lines += [f"  {path}" for path in conflicted[:MAX_REPORTED]]
    if len(conflicted) > MAX_REPORTED:
        lines.append(f"  ... and {len(conflicted) - MAX_REPORTED} more")
    lines += [
        "",
        "Resolve them, then `git add` the file again. `git diff --check` lists the",
        "exact lines. If both sides are right, keep both: that is the usual answer",
        "for a documentation overlay, where the two halves describe different things.",
    ]
    return "\n".join(lines)


def read_staged_blobs(staged):
    """The staged content of every staged file, read once, keyed by path.

    EVERY staged file, not only the staged tests: most tears are not tests at
    all (a step file needing its sibling, a page needing its stylesheet, a doc
    row needing its script). The cost is one `git show` per staged file, tens of
    milliseconds for a forty-file commit, and the conflict-marker check needs
    every staged blob anyway. A deleted import line is beyond any reference
    walk: nothing references a file except the line that went missing.
    """
    return {path: staged_blob(path) for path in staged}


def main():
    """Exit 1 on a torn commit, 0 on anything else. Never raises."""
    if os.environ.get("TORN_GUARD", "1") == "0":
        return 0
    if not in_a_repo():
        amber("not inside a git working tree")
        return 0

    staged = staged_paths()
    if staged is None:
        amber("could not list the staged paths")
        return 0
    if not staged:
        return 0

    blobs = read_staged_blobs(staged)
    if not blobs:
        return 0

    conflicted = staged_files_with_conflict_markers(blobs)
    if conflicted:
        print(conflict_report(conflicted), file=sys.stderr)
        return 1

    broken = sourced_shell_contract_breaks(staged, blobs)
    if broken:
        print(contract_report(broken), file=sys.stderr)
        return 1

    dirty = dirty_paths(staged)
    if dirty is None:
        amber("could not list the working-tree changes")
        return 0
    if not dirty:
        return 0
    if len(dirty) > MAX_DIRTY:
        amber(f"{len(dirty)} uncommitted paths is more than this guard reasons about")
        return 0

    found = findings(blobs, dirty, RepoIndex())
    if not found:
        return 0

    unseen = never_committed(staged)
    if unseen is None:
        amber("could not tell tracked paths from untracked; nothing blocked")
        return 0

    torn = [pair for pair in found if blocks(pair, unseen)]
    stale = [pair for pair in found if not blocks(pair, unseen)]
    if stale:
        print(warn(stale), file=sys.stderr)
    if torn:
        print(report(torn), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception as error:  # fail-open: a broken guard must not wedge a commit
        print(f"torn-commit guard could not run ({error}); commit allowed", file=sys.stderr)
        status = 0
    for line in _AMBER:
        print(f"torn-commit guard: {line}", file=sys.stderr)
    sys.exit(status)
