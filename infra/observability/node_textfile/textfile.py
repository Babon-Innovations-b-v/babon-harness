"""Write a node-exporter textfile atomically.

node-exporter reads every `*.prom` file in HARNESS_TEXTFILE_DIR (default
`/var/lib/harness/textfile`, mounted read-only into the node-exporter
container). Render to a temporary file and rename, so a scrape never sees half
a file.
"""
from __future__ import annotations

import os
from pathlib import Path


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
