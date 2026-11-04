"""Publish a job's metrics: a node-exporter textfile on a server, the
Pushgateway in the cluster.

On a server, node-exporter reads every `*.prom` file in HARNESS_TEXTFILE_DIR
(default `/var/lib/harness/textfile`, mounted read-only into the node-exporter
container). Render to a temporary file and rename, so a scrape never sees half
a file.

In the cluster there is no shared textfile directory: a CronJob's pod is gone
when it ends. With PUSHGATEWAY_URL set, `publish` replaces the job's group on
the Pushgateway instead (`PUT <url>/metrics/job/<name>`), and Prometheus reads
its freshness from `push_time_seconds{job="<name>"}`.

FAILURE POLICY: a refused or unreachable push raises (URLError is an OSError),
the same as a textfile that cannot be written; the caller decides whether the
metric is worth its run.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

PUSH_TIMEOUT_S = 10


def textfile_dir() -> Path:
    return Path(os.environ.get("HARNESS_TEXTFILE_DIR", "/var/lib/harness/textfile"))


def write_textfile(name: str, lines: list[str]) -> Path:
    """Write `lines` to `<textfile_dir>/<name>.prom` atomically and return the path."""
    directory = textfile_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.prom"
    temporary = directory / f".{name}.prom.{os.getpid()}"
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o644)
    temporary.replace(target)
    return target


def push_request(base_url: str, name: str, lines: list[str]) -> urllib.request.Request:
    """The PUT that replaces job `name`'s whole group on the Pushgateway at `base_url`."""
    return urllib.request.Request(
        f"{base_url.rstrip('/')}/metrics/job/{name}",
        data=("\n".join(lines) + "\n").encode(),
        method="PUT",
        headers={"Content-Type": "text/plain; version=0.0.4"},
    )


def publish(name: str, lines: list[str]) -> None:
    """Push `lines` as job `name` when PUSHGATEWAY_URL is set, else write the textfile."""
    base_url = os.environ.get("PUSHGATEWAY_URL", "").strip()
    if not base_url:
        write_textfile(name, lines)
        return
    with urllib.request.urlopen(push_request(base_url, name, lines), timeout=PUSH_TIMEOUT_S):
        pass
