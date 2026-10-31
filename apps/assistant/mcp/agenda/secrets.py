"""load_credentials(): the CalDAV root and the login, from the environment.

The values come from the vault through the server's environment file, so
nothing is read from disk here and nothing is cached beyond the process.

FAILURE POLICY: fail-loud. A missing setting raises SecretsUnavailable naming
it, so a client sees which one to fill rather than an auth error.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class SecretsUnavailable(RuntimeError):
    """A CalDAV setting is missing. Carries the operator-facing reason."""


@dataclass(frozen=True)
class CalDavCredentials:
    base_url: str
    user: str
    app_password: str


def load_credentials() -> CalDavCredentials:
    """AGENDA_BASE_URL, AGENDA_USER and AGENDA_APP_PASSWORD, all required."""
    values = {
        name: os.environ.get(name, "").strip()
        for name in ("AGENDA_BASE_URL", "AGENDA_USER", "AGENDA_APP_PASSWORD")
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SecretsUnavailable(
            f"{', '.join(missing)} not set. Fill them in config/harness.env "
            "(AGENDA_BASE_URL) and the vault (AGENDA_USER, AGENDA_APP_PASSWORD)."
        )
    return CalDavCredentials(
        base_url=values["AGENDA_BASE_URL"],
        user=values["AGENDA_USER"],
        app_password=values["AGENDA_APP_PASSWORD"],
    )
