"""dashkit.core.audit: per-domain activity log (audit trail).

Each dashboard owns its own ``{domain}_activity`` table with the same
schema; functions are parameterised by table name so every dashboard
shares one implementation.

Schema (identical for every domain):

    id           BIGSERIAL PRIMARY KEY
    action_type  TEXT NOT NULL
    user_name    TEXT NOT NULL
    doc_path     TEXT
    section_id   TEXT
    detail       JSONB
    created_at   TIMESTAMPTZ DEFAULT NOW()

Module map (one public callable per file):

    log_activity.py    log_activity(conn, table_name, ...), one row, best-effort
    fetch_activity.py  fetch_activity(conn, table_name, limit), newest-first reads
    table.py           ensure_activity_table(conn, table_name) lazy CREATE TABLE
                       + per-process ready flags

FAILURE POLICY: writes are best-effort: an audit-log failure
must never break the feature being audited; the swallow is documented
at the site in ``log_activity``. Reads PROPAGATE so a broken audit
surface is visible in the dashboard instead of rendering empty.
"""
from __future__ import annotations

from dashkit.core.audit.fetch_activity import (
    fetch_activity,
)
from dashkit.core.audit.log_activity import log_activity
from dashkit.core.audit.table import (
    ensure_activity_table,
)

__all__ = [
    "ensure_activity_table",
    "fetch_activity",
    "log_activity",
]
