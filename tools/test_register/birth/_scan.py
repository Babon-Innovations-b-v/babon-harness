"""What a test reads that is not its own synthetic ground truth.

OWNS: the static half of the birth check: reading one python test's
source and naming every place it reads the live machine, the wall clock or the
network instead of an input it built itself.

DOES NOT OWN: when it runs (`__main__.py --check --base`, the rows a change
adds), or the sealed run that catches what reading the source cannot (the
pre-commit hook runs a new test in the pinned gate image with the network off
and a fixed fake clock).

WHY. A test checks one purpose against a synthetic ground truth: the made-up
input and known answer built inside the test (CONTEXT.md). A test that reads
the live box, the clock or the network judges the machine and the day, not the
commit, and its verdict changes with neither. So it is refused when it is born,
rather than quarantined after it has already turned a commit red.

WHAT IT LOOKS AT, by syntax tree and never by text, so a docstring or a comment
that names `/opt` or `time.time()` is not a finding:

  the clock      `time.time()`, `time.time_ns()`, `datetime.now()`,
                 `datetime.utcnow()`, `datetime.today()`, `date.today()`, and
                 `time.localtime()`, `time.gmtime()` or `time.ctime()` called
                 with no argument
  the network    importing `socket`, `requests`, `httpx`, `urllib.request`,
                 `http.client`, `urllib3`, `aiohttp`, `websocket(s)`,
                 `paramiko`, `smtplib` or `ftplib`, or calling `urlopen`
  the machine    a path under /opt, /var/lib, /etc, /proc, /sys, /run, /root or
                 /home given straight to `Path`, `open` or an `os`, `os.path`,
                 `glob` or `shutil` read; `Path.home()` and `expanduser`; the
                 host's name (`gethostname`, `platform.node`, `uname`); and
                 `docker`, `kubectl`, `systemctl`, `journalctl`, `ssh`, `scw` or `gh`
                 run through `subprocess` or `os.system`, or looked up with
                 `shutil.which`

A fake `kubectl` the test writes into its own `tmp_path` is not a finding: the
command it runs is the stub's path, not the bare word.

FAILURE POLICY. Pure: reads the source it is given and nothing else.
"""
from __future__ import annotations

import ast

_CLOCK_ALWAYS = {("time", "time"), ("time", "time_ns"), ("datetime", "now"), ("datetime", "utcnow"),
                 ("datetime", "today"), ("date", "today")}
_CLOCK_WITHOUT_ARGUMENT = {("time", "localtime"), ("time", "gmtime"), ("time", "ctime")}
_NETWORK_MODULES = ("socket", "requests", "httpx", "urllib.request", "http.client", "urllib3",
                    "aiohttp", "websocket", "websockets", "paramiko", "smtplib", "ftplib")
_LIVE_PREFIXES = ("/opt", "/var/lib", "/etc", "/proc", "/sys", "/run", "/root", "/home")
_PATH_READERS = {"Path", "PurePath", "PosixPath", "open", "exists", "isfile", "isdir", "getmtime",
                 "getsize", "listdir", "stat", "scandir", "walk", "glob", "iglob", "copy", "copy2",
                 "copyfile", "copytree", "read_text", "read_bytes"}
_COMMAND_RUNNERS = {"run", "call", "check_call", "check_output", "Popen", "system", "popen", "getoutput",
                    "getstatusoutput"}
_LIVE_COMMANDS = ("docker", "kubectl", "systemctl", "journalctl", "ssh", "scw", "gh")
_HOST_NAMES = {("socket", "gethostname"), ("platform", "node"), ("os", "uname"), ("Path", "home")}


def live_reads(source: str) -> tuple[str, ...]:
    """Every place `source` reads the live machine, the clock or the network, as sentences.

    Empty for a test that only reads what it built. A source that does not
    parse is one sentence saying so, because a test nobody can read cannot be
    shown to be sealed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as failure:
        return (f"line {failure.lineno}: the file does not parse, so nothing shows it is sealed",)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.extend(_network_import(node))
        elif isinstance(node, ast.Call):
            found.extend(_call_finding(node))
    return tuple(sorted(set(found), key=lambda sentence: int(sentence.split(":", 1)[0].split()[1])))


def _network_import(node: ast.Import | ast.ImportFrom) -> list[str]:
    """An import of a module whose only use is talking over the network."""
    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
    if isinstance(node, ast.ImportFrom) and node.module == "urllib":
        names = [f"urllib.{alias.name}" for alias in node.names]
    return [
        f"line {node.lineno}: imports {name}, which reads the network"
        for name in names
        if any(name == module or name.startswith(f"{module}.") for module in _NETWORK_MODULES)
    ]


def _call_finding(node: ast.Call) -> list[str]:
    """What one call reads, if it reads the clock, the machine or the network."""
    owner, name = _callee(node.func)
    line = node.lineno
    if (owner, name) in _CLOCK_ALWAYS or ((owner, name) in _CLOCK_WITHOUT_ARGUMENT and not node.args):
        return [f"line {line}: {owner}.{name}() reads the wall clock"]
    if name == "urlopen":
        return [f"line {line}: urlopen() reads the network"]
    if (owner, name) in _HOST_NAMES or name == "expanduser":
        return [f"line {line}: {owner + '.' if owner else ''}{name}() reads this machine"]
    if name == "which" and _first_word(node) in _LIVE_COMMANDS:
        return [f"line {line}: looks for {_first_word(node)} on this machine"]
    if name in _COMMAND_RUNNERS and _first_word(node) in _LIVE_COMMANDS:
        return [f"line {line}: runs {_first_word(node)}, which reads this machine"]
    if name in _PATH_READERS and _live_path(node):
        return [f"line {line}: {name}() reads {_live_path(node)} on this machine"]
    return []


def _callee(func: ast.expr) -> tuple[str, str]:
    """(`owner`, `name`) of a call: `datetime.datetime.now` is ("datetime", "now")."""
    if isinstance(func, ast.Attribute):
        value = func.value
        owner = value.attr if isinstance(value, ast.Attribute) else getattr(value, "id", "")
        return owner, func.attr
    if isinstance(func, ast.Name):
        return "", func.id
    return "", ""


def _first_argument(node: ast.Call) -> ast.expr | None:
    """The call's first positional argument, or the first item of a list or tuple given there."""
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        return first.elts[0] if first.elts else None
    return first


def _first_word(node: ast.Call) -> str:
    """The command a call names: the first word of its first argument, when that is a literal."""
    first = _first_argument(node)
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        words = first.value.split()
        return words[0] if words else ""
    return ""


def _live_path(node: ast.Call) -> str:
    """The live path a call is given as a literal, or ''."""
    first = node.args[0] if node.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        path = first.value
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in _LIVE_PREFIXES):
            return path
    return ""
