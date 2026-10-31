"""the assistant's knowledge base, one searchable index over the durable
sources of truth: the bible, the ADRs, soul, CONTEXT, and every issue.

`search(query)` is the seam the loops use; it reads a warm index and never
rebuilds inline. `start_reindexer()` (called from the container entrypoint) keeps
the index fresh in the background: an eager build at cold start, then every
30 min. Backed by SQLite FTS5 on the shared connection, so it lives in the
pod like the rest of the assistant's memory. The bible + ADRs are read from the
image's `docs/`, soul + CONTEXT + issues + the assistant's own journal and weekly
compacts are folded in too.

Public callables: `search`, `ensure_fresh`, `rebuild`, `start_reindexer`.
"""
from __future__ import annotations

from apps.assistant.core.knowledge.index import (
    ensure_fresh,
    rebuild,
    search,
    start_reindexer,
)

__all__ = ["search", "ensure_fresh", "rebuild", "start_reindexer"]
