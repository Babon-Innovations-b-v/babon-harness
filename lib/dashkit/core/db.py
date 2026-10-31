"""The database connection every dashkit dashboard uses.

One PostgreSQL database in the stack holds every table dashkit touches:
``{domain}_activity``, ``{domain}_ai_calls``, ``{domain}_sync_status``
and ``dashkit_*``. The connection string is, in order:

1. ``DB_URL`` when set (compose builds it for each app container),
2. ``DB_URL_OPS`` when set (an external DSN, used from outside the
   docker network, for example by GPU workers),
3. otherwise assembled from ``POSTGRES_USER``, ``POSTGRES_PASSWORD``,
   ``POSTGRES_DB`` and ``POSTGRES_HOST`` (default ``postgres``, the
   compose service name).

dashkit is self-contained: keep this module free of imports from
application code.

FAILURE POLICY: ``get_db()`` fails OPEN (returns None) when no
connection string can be built or the database is down, so routes can
degrade to 503 or an empty payload; routes that require the database
raise 503 on None.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

import psycopg


def dsn() -> str:
    """The connection string, re-read from the environment on every call."""
    explicit = os.environ.get("DB_URL") or os.environ.get("DB_URL_OPS")
    if explicit:
        return explicit
    user = os.environ.get("POSTGRES_USER", "")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (user and database):
        return ""
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )


def get_db() -> Optional[psycopg.Connection]:
    """Return a fresh connection, or None if the database is unreachable."""
    conninfo = dsn()
    if not conninfo:
        return None
    try:
        return psycopg.connect(conninfo)
    except psycopg.Error:
        return None
