"""Pins that a dashboard built by the factory serves dashkit's frontend
and refuses to serve anything outside it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dashkit import DashkitConfig, make_dashboard_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key in ("DB_URL", "DB_URL_OPS", "POSTGRES_USER", "POSTGRES_DB"):
        monkeypatch.delenv(key, raising=False)
    app = make_dashboard_app(DashkitConfig(
        domain="demo",
        title="Demo",
        activity_table="demo_activity",
        ai_calls_table="demo_ai_calls",
        sync_status_table="demo_sync_status",
        sync_token_env_var="DEMO_HEARTBEAT_TOKEN",
    ))
    return TestClient(app)


def test_base_css_is_served(client: TestClient) -> None:
    resp = client.get("/static/dashkit/base.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert "--color-" in resp.text


def test_path_traversal_is_refused(client: TestClient) -> None:
    # Percent-encoded so the client cannot normalise the dots away; the
    # route receives "../core/db.py" and must refuse it.
    resp = client.get("/static/dashkit/..%2Fcore%2Fdb.py")
    assert resp.status_code == 404


def test_no_database_degrades_to_empty_audit_log(client: TestClient) -> None:
    assert client.get("/api/audit-log").json() == {"activity": [], "total": 0}


def test_heartbeat_without_token_configured_is_503(client: TestClient) -> None:
    resp = client.post("/api/internal/sync-heartbeat",
                       json={"status": "ok", "duration_ms": 1})
    assert resp.status_code == 503
