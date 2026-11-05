"""The agenda server binds loopback unless told, and names every calendar setting it is missing.

WHAT IT PINS. The agenda server's own code, beside its `ical` and `tools`
modules: `serve` runs on stdio by default, refuses a network transport with no
port, binds 127.0.0.1 unless a host is named (the server reads calendars and
authenticates no caller), and lets only the address it bound past the
library's rebinding check; `load_credentials` raises `SecretsUnavailable`
naming every missing CalDAV setting. The MCP server is a recorder of how it was
run.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each argv and
environment is made up here, and the expected run is written out from the
module's stated defaults and rules; the refusal names the variables the case
left empty, in the order the module documents them.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row binds every
address by default, so the port-only case binds 0.0.0.0.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

serve_module = importlib.import_module("apps.assistant.mcp.agenda.serve")
secrets_module = importlib.import_module("apps.assistant.mcp.agenda.secrets")

FULL = {"AGENDA_BASE_URL": "https://cloud.example.org/remote.php/dav", "AGENDA_USER": "assistant",
        "AGENDA_APP_PASSWORD": "made-up"}


def _served(argv: list[str]) -> tuple:
    """How the server was run: (transport, host, port, allowed hosts), or the refusal."""
    runs: list = []
    security = SimpleNamespace(allowed_hosts=[], allowed_origins=[])
    mcp = SimpleNamespace(settings=SimpleNamespace(host=None, port=None, transport_security=security),
                          run=lambda transport="stdio": runs.append(transport))
    try:
        serve_module.serve(mcp, argv)
    except SystemExit:
        return ("refused",)
    return runs[0], mcp.settings.host, mcp.settings.port, security.allowed_hosts


def _credentials() -> str:
    """The user the settings load as, or the names the refusal gives."""
    try:
        return secrets_module.load_credentials().user
    except secrets_module.SecretsUnavailable as refusal:
        return str(refusal).split(" not set", 1)[0]


CASES = [
    pytest.param([], (), ("stdio", None, None, []), id="stdio-by-default"),
    pytest.param(["--transport", "sse"], (), ("refused",), id="a-network-transport-needs-a-port"),
    pytest.param(["--transport", "sse", "--port", "9300"], (), ("sse", "127.0.0.1", 9300, []),
                 id="loopback-unless-told"),
    pytest.param(["--transport", "streamable-http", "--host", "10.0.0.5", "--port", "9300"], (),
                 ("streamable-http", "10.0.0.5", 9300, ["10.0.0.5:9300", "10.0.0.5"]),
                 id="only-the-bound-address-is-let-through"),
    pytest.param(None, (), "assistant", id="every-setting-present"),
    pytest.param(None, ("AGENDA_APP_PASSWORD",), "AGENDA_APP_PASSWORD", id="one-missing-named"),
    pytest.param(None, ("AGENDA_BASE_URL", "AGENDA_APP_PASSWORD"), "AGENDA_BASE_URL, AGENDA_APP_PASSWORD",
                 id="every-missing-one-named"),
]


@pytest.mark.parametrize("argv, missing, expected", CASES)
def test_the_agenda_server_binds_loopback_unless_told_and_names_every_calendar_setting_it_is_missing(
        argv: list | None, missing: tuple, expected: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """How the server ran (argv given), or what the settings said (argv None), is the hand-written answer."""
    for name in ("AGENDA_MCP_TRANSPORT", "AGENDA_MCP_HOST", "AGENDA_MCP_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in FULL.items():
        monkeypatch.setenv(name, "" if name in missing else value)
    assert (_served(argv) if argv is not None else _credentials()) == expected
