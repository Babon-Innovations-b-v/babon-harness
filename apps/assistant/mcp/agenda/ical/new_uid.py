"""new_uid(), a fresh event UID in the ``@harness-agenda`` namespace.

The suffix matters: client.py fetches events by the deterministic URL
``{uid}.ics``, and the live smoke test recognises its own throwaway events
by this marker.
"""
from __future__ import annotations

import uuid


def new_uid() -> str:
    return f"{uuid.uuid4()}@harness-agenda"
