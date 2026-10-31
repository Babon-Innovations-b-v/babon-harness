"""Textfile collector: container restarts and failed harness units, every minute.

Run by `harness-textfile.timer`. Writes two files node-exporter publishes:

- `containers.prom`: `harness_container_up{name}` and
  `harness_container_restarts_total{name}` for every container, read with
  `docker inspect`. Set HARNESS_COMPOSE_PROJECT to keep only one compose
  project's containers.
- `units.prom`: `harness_systemd_unit_failed{unit}` for every loaded
  `harness-*` unit (1 when failed), and `harness_textfile_last_run_timestamp_seconds`,
  which a rule watches so a dead collector cannot read as a quiet box.

FAILURE POLICY: a command that cannot run leaves its file unwritten (stale
data ages out through the last-run rule), and the run exits non-zero so the
failure handler pages.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from infra.observability.node_textfile.textfile import write_textfile


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30, check=True).stdout


def container_lines(inspected: list[dict]) -> list[str]:
    """Render `docker inspect` records as metric lines."""
    lines = [
        "# HELP harness_container_up 1 when the container is running.",
        "# TYPE harness_container_up gauge",
        "# HELP harness_container_restarts_total RestartCount from docker inspect.",
        "# TYPE harness_container_restarts_total counter",
    ]
    for record in inspected:
        name = _escape((record.get("Name") or "").lstrip("/"))
        running = 1 if (record.get("State") or {}).get("Running") else 0
        lines.append(f'harness_container_up{{name="{name}"}} {running}')
        lines.append(f'harness_container_restarts_total{{name="{name}"}} {int(record.get("RestartCount") or 0)}')
    return lines


def unit_lines(listing: str, now: float) -> list[str]:
    """Render `systemctl list-units --plain --no-legend` output as metric lines."""
    lines = [
        "# HELP harness_systemd_unit_failed 1 when a harness unit is in the failed state.",
        "# TYPE harness_systemd_unit_failed gauge",
    ]
    for row in listing.splitlines():
        fields = row.split()
        if len(fields) < 3:
            continue
        unit, active = fields[0], fields[2]
        lines.append(f'harness_systemd_unit_failed{{unit="{_escape(unit)}"}} {1 if active == "failed" else 0}')
    lines += [
        "# HELP harness_textfile_last_run_timestamp_seconds Last time the textfile collector ran.",
        "# TYPE harness_textfile_last_run_timestamp_seconds gauge",
        f"harness_textfile_last_run_timestamp_seconds {int(now)}",
    ]
    return lines


def main() -> int:
    failed = False
    try:
        project = os.environ.get("HARNESS_COMPOSE_PROJECT", "").strip()
        ps_args = ["ps", "-aq"] + (["--filter", f"label=com.docker.compose.project={project}"] if project else [])
        ids = _docker(*ps_args).split()
        inspected = json.loads(_docker("inspect", *ids)) if ids else []
        write_textfile("containers", container_lines(inspected))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"container metrics not written: {exc}", file=sys.stderr)
        failed = True
    try:
        listing = subprocess.run(
            ["systemctl", "list-units", "harness-*", "--all", "--plain", "--no-legend"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        write_textfile("units", unit_lines(listing, time.time()))
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"unit metrics not written: {exc}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
