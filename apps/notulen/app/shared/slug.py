"""Filename-safe slug for notulen titles.

One home for the slug grammar: the git target path
(``core.publish.github.target_path``), the AI-call ``doc_path`` label, and the
download filename all derive from this function.
"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug (<=60 chars, lowercase)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    return text[:60]
