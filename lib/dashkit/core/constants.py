"""Shared infrastructure settings for the dashkit ecosystem.

Plain environment reads with neutral defaults, defined here rather than
imported, so dashkit stays self-contained: lean images copy only the
``dashkit`` directory. The values come from ``config/harness.env`` (and
the vault copy of it) through docker compose.

Model defaults live in the ``dashkit_ai_config`` table read by
``dashkit.ai``, not here.
"""

from __future__ import annotations

import os

S3_BUCKET: str = os.environ.get("S3_BUCKET", "")
S3_REGION: str = os.environ.get("S3_REGION", "")
SCW_REGION: str = os.environ.get("SCW_REGION", "fr-par")

__all__ = [
    "S3_BUCKET",
    "S3_REGION",
    "SCW_REGION",
]
