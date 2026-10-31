"""Read-only shell tool, a bounded terminal for non-invasive checks
(look things up and run non-invasive isolated tests).

This stays inside the read-only advisor boundary: it can run
only commands that observe, never commands that change infrastructure.
Three locks, defense-in-depth (same doctrine as db_query / scw_read):

  1. NO SHELL. The command is split with ``shlex`` and run with
     ``subprocess.run([...], shell=False)``. There is no shell to
     interpret ``;`` ``|`` ``&&`` ``$()`` ``>`` backticks, those become
     literal arguments to the one binary, which simply errors. So a
     single call is exactly one process, no chaining, no redirection,
     no injection.
  2. BINARY ALLOWLIST. ``argv[0]`` must be one of a fixed set of
     read-only investigation tools. Anything else is refused before
     execution.
  3. PER-BINARY ARGUMENT GUARDS. Even an allowlisted binary is refused
     if an argument looks mutating (curl -d/-X POST, a redirect target,
     a kubectl write verb, a file-writing flag). Deny-by-default.

Plus: a hard timeout, an output cap, and the container's own IAM is read-only
anyway (SecretManagerReadOnly + cluster READ), so even kubectl here can
only read. Secret env is scrubbed from the child so a command can't
echo the container's own credentials.

Tool-module grammar: ``NAME``, ``DEFINITION``, ``execute``.

FAILURE POLICY: Tier-2, a refused or failed command returns a clear
string the LLM reacts to, never raises. A refusal explains why so the
model can pick a different check.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess

from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.tools.run_shell")

NAME = "run_shell"

_TIMEOUT_S = 20
_MAX_OUTPUT = 6000

# argv[0] -> the read-only verbs/flags it may use. An empty allowed-verb
# set means "any args allowed" (the binary is read-only by nature, e.g.
# dig). A binary NOT in this map is refused outright.
_ALLOWED: dict[str, dict] = {
    # DNS / reachability, inherently read-only.
    "dig": {},
    "nslookup": {},
    "host": {},
    "getent": {},
    "ping": {"require": ["-c"], "note": "ping needs a -c count cap"},
    # TCP connect probe only (no data). -z = scan/zero-IO.
    "nc": {"require": ["-z"], "note": "nc is allowed only as a -z connect test"},
    "ncat": {"require": ["-z"]},
    # HTTP: GET/HEAD only. Deny bodies, methods, uploads, file writes.
    "curl": {
        "deny": ["-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
                 "-X", "--request", "-T", "--upload-file", "-F", "--form",
                 "-o", "--output", "-O", "--remote-name"],
        "note": "curl is read-only: no -d/-X/-T/-F/-o (GET/HEAD only)",
    },
    "wget": {
        "require_any": ["--spider"],
        "deny": ["--post-data", "--post-file", "-O", "--output-document",
                 "--method"],
        "note": "wget is allowed only with --spider (no download)",
    },
    # TLS/cert inspection, read-only.
    "openssl": {"first": ["s_client", "x509", "version"]},
    # Cluster reads. kubectl in the container is RBAC-read-only anyway; verbs
    # are pinned belt-and-suspenders.
    "kubectl": {"first": ["get", "describe", "logs", "top", "events",
                          "version", "api-resources", "explain"]},
}

# Args that are dangerous under ANY binary (shell-redirect residue etc.).
_GLOBAL_DENY = {">", ">>", "<", "|", ";", "&", "&&", "||", "`", "$("}

# Env keys to scrub from the child so a command can't print the container's
# own secrets (its RO creds, webhook secret, DB URL, bearer).
_SECRET_ENV_PREFIXES = ("OPENCLAW_", "SIGNAL_", "ANTHROPIC_", "SCW_", "DB_URL")


DEFINITION = {
    "name": NAME,
    "description": (
        "One read-only check: dig, nslookup, host, getent, ping -c, nc -z, curl "
        "or wget GET/HEAD, openssl s_client/x509, kubectl get/describe/logs. No "
        "pipes, redirects, chaining or $(); anything that could change "
        "infrastructure is refused. Report the finding, never the command."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "e.g. 'dig +short api.example.org'.",
            },
        },
        "required": ["command"],
    },
}


def _refuse(reason: str) -> str:
    return f"refused: {reason}"


def _check(argv: list[str]) -> str | None:
    """Return a refusal reason, or None if the command is allowed."""
    if not argv:
        return "empty command"
    for token in argv:
        if token in _GLOBAL_DENY:
            return (
                f"{token!r} is a shell operator; this tool runs ONE command "
                "with no shell (no pipes/redirects/chaining)"
            )
    binary = os.path.basename(argv[0])
    spec = _ALLOWED.get(binary)
    if spec is None:
        return (
            f"{binary!r} is not on the read-only allowlist. Allowed: "
            + ", ".join(sorted(_ALLOWED))
        )
    args = argv[1:]
    if "first" in spec and (not args or args[0] not in spec["first"]):
        return f"{binary} allows only these subcommands: {', '.join(spec['first'])}"
    if "deny_first" in spec and args and args[0] in spec["deny_first"]:
        return f"{binary} {args[0]!r} is a mutating subcommand; read-only only"
    for verb in spec.get("deny_any", []):
        if verb in args:
            return f"{binary} {verb!r} is a mutating verb; read-only only"
    for flag in spec.get("deny", []):
        if flag in args or any(a.startswith(flag + "=") for a in args):
            return spec.get("note", f"{binary} {flag} is not allowed (read-only only)")
    for flag in spec.get("require", []):
        if flag not in args:
            return spec.get("note", f"{binary} requires {flag} for this tool")
    if "require_any" in spec and not any(f in args for f in spec["require_any"]):
        return spec.get("note", f"{binary} requires one of {spec['require_any']}")
    return None


def _clean_env() -> dict:
    return {
        key: val
        for key, val in os.environ.items()
        if not any(key.startswith(prefix) for prefix in _SECRET_ENV_PREFIXES)
    }


def execute(tool_input: dict) -> str:
    command = str(tool_input.get("command", "")).strip()
    if not command:
        return _refuse("no command given")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _refuse(f"could not parse command ({exc})")
    reason = _check(argv)
    if reason is not None:
        return _refuse(reason)
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            env=_clean_env(),
            check=False,
        )
    except FileNotFoundError:
        return _refuse(f"{argv[0]!r} is not installed in the pod")
    except subprocess.TimeoutExpired:
        return f"timed out after {_TIMEOUT_S}s: {command}"
    except Exception as exc:  # noqa: BLE001, Tier-2: never raise into the loop
        log.warning("run_shell failed: %s", exc)
        return f"command error: {exc}"
    body = (result.stdout or "") + (result.stderr or "")
    header = f"$ {command}\n(exit {result.returncode})\n"
    return truncate(header + body.strip())
