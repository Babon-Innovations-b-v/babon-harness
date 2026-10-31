"""The assistant's display name, read once from ASSISTANT_NAME.

Every prompt, tool description and message that names the assistant reads
this constant, so one setting renames it everywhere. The default is
deliberately plain.
"""
from __future__ import annotations

import os

ASSISTANT_NAME: str = os.environ.get("ASSISTANT_NAME", "").strip() or "Assistant"

__all__ = ["ASSISTANT_NAME"]
