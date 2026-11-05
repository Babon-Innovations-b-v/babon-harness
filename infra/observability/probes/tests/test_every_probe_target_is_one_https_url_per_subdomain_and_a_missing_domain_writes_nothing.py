"""Every probe target is one https URL per subdomain, and a missing domain writes nothing.

WHAT IT PINS. `infra.observability.probes.render_targets.main`, the init
container Prometheus waits on: from DOMAIN and PROBE_SUBDOMAINS it writes the
file_sd JSON the blackbox exporter probes, and with no DOMAIN it exits 1 and
writes no file, so Prometheus never starts on an empty list that looks healthy.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The made-up
domain and subdomain lists are expanded by hand: `@` is the bare domain, every
other label is `<label>.<domain>`, each becomes `https://<host>/`, blanks are
skipped and a repeat appears once, in the order given.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row keeps
repeated targets, so the repeat case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
import json

import pytest

render_targets = importlib.import_module("infra.observability.probes.render_targets")

CASES = [
    pytest.param(
        "example.org", None,
        (0, ["https://example.org/", "https://cloud.example.org/", "https://notulen.example.org/"]),
        id="the-default-three",
    ),
    pytest.param(
        "example.org", "status, @,,status,mail",
        (0, ["https://status.example.org/", "https://example.org/", "https://mail.example.org/"]),
        id="blanks-skipped-and-a-repeat-once",
    ),
    pytest.param("", "@", (1, None), id="no-domain-writes-nothing"),
]


@pytest.mark.parametrize("domain, subdomains, expected", CASES)
def test_every_probe_target_is_one_https_url_per_subdomain_and_a_missing_domain_writes_nothing(
        domain: str, subdomains: str | None, expected: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """(exit code, targets written) is the hand-expanded one."""
    target = tmp_path / "targets" / "probes.json"
    monkeypatch.setenv("DOMAIN", domain)
    monkeypatch.setenv("PROBE_TARGETS_FILE", str(target))
    if subdomains is None:
        monkeypatch.delenv("PROBE_SUBDOMAINS", raising=False)
    else:
        monkeypatch.setenv("PROBE_SUBDOMAINS", subdomains)
    code = render_targets.main()
    written = json.loads(target.read_text())[0]["targets"] if target.exists() else None
    assert (code, written) == expected
