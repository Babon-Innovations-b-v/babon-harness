"""Write the HTTPS probe targets Prometheus reads, from DOMAIN.

Prometheus cannot read environment variables in its own config, so this runs
as a one-shot container before Prometheus starts (`probe-targets` in
compose.yml) and writes a file_sd JSON file to a shared volume. Prometheus
re-reads the file by itself when it changes.

Inputs: DOMAIN (required), PROBE_SUBDOMAINS (comma-separated, default
"@,cloud,notulen"; "@" is the bare domain), PROBE_TARGETS_FILE (default
/targets/probes.json). Every target is probed at `https://<host>/` by the
blackbox exporter, which yields both up/down and the certificate's expiry.

FAILURE POLICY: a missing DOMAIN exits 1, so compose shows the init container
failed and Prometheus does not start with an empty target list pretending all
is well.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def probe_urls(domain: str, subdomains: str) -> list[str]:
    """`https://` URLs for each subdomain of `domain`, in order, without repeats."""
    urls: list[str] = []
    for entry in subdomains.split(","):
        label = entry.strip()
        if not label:
            continue
        host = domain if label == "@" else f"{label}.{domain}"
        url = f"https://{host}/"
        if url not in urls:
            urls.append(url)
    return urls


def main() -> int:
    domain = os.environ.get("DOMAIN", "").strip()
    if not domain:
        print("DOMAIN is not set: no probe targets written", file=sys.stderr)
        return 1
    urls = probe_urls(domain, os.environ.get("PROBE_SUBDOMAINS", "@,cloud,notulen"))
    target = Path(os.environ.get("PROBE_TARGETS_FILE", "/targets/probes.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps([{"targets": urls, "labels": {"probe": "https"}}], indent=2) + "\n")
    temporary.replace(target)
    print(f"wrote {len(urls)} probe targets to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
