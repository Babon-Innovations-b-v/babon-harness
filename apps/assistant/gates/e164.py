"""E.164 normalisation shared by the gate adapters.

`gates.allowlist` (admission check) and `gates.signal` (inbound parse)
must compare sender numbers byte-stably, so the strip-spaces rule lives
in exactly one home, a public seam, since 2+ sibling modules import it
(module standard §2;: one public callable per file).

FAILURE POLICY: pure string transform, nothing to fail.
"""
from __future__ import annotations


def normalize_number(number: str) -> str:
    """Strip spaces so comparison is byte-stable across the
    `+15550100099` vs `+15550100099` formatting Signal clients emit."""
    return number.replace(" ", "").strip()
