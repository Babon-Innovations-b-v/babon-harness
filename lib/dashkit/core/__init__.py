"""dashkit.core: bootstrap and observability primitives for the dashboards.

Module map (one public callable per file):

    app_factory.py        make_dashboard_app(config) (+ DashkitConfig), the
                          one entry every dashboard calls
    auth.py               get_user(headers), the SSO identity oauth2-proxy
                          hands over through Caddy
    db.py                 get_db() (+ dsn()), connections to the stack database
    constants.py          S3_BUCKET / S3_REGION / SCW_REGION from the environment
    inspector.py          run_checks(conn, checks) (+ HealthCheck)
    audit/                per-domain {domain}_activity log (package)
    sync/                 sync-status table + heartbeat router (package)
    identifiers.py        validate_table_name(name), the SQL table-name gate
    _frontend_static.py   /static/dashkit/* route (internal to app_factory)
"""
from __future__ import annotations

from dashkit.core.app_factory import (
    DashkitConfig,
    make_dashboard_app,
)
from dashkit.core.auth import get_user
from dashkit.core.db import get_db
from dashkit.core.identifiers import validate_table_name

__all__ = [
    "DashkitConfig",
    "get_db",
    "get_user",
    "make_dashboard_app",
    "validate_table_name",
]
