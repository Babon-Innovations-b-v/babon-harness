"""CLI entrypoint: `python -m apps.assistant.watch <pass>`.

The exec line of the five units in `apps/assistant/systemd/`. Kept separate from `run.py` so running the
package does not re-import that module as `__main__` after the seam already
imported it (the runpy double-import warning), and so the dispatch and its exit
contracts stay importable by a test.

Module path is a deploy interface: the unit files name it AND the subcommand, so
renaming either means regenerating the units in the same commit.
"""
from __future__ import annotations

import logging
import sys

from apps.assistant.watch import run

logging.basicConfig(level=logging.INFO)
sys.exit(run.main(sys.argv[1:]))
