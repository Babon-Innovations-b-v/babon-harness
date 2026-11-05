"""A heartbeat lands only with the right bearer and a known status, and a never-run job reads stale.

WHAT IT PINS. `dashkit.core.sync`: the router `make_heartbeat_router` builds
answers 503 while its token is unset, 401 on any other bearer, 400 on a status
that is neither `ok` nor `fail`, and otherwise writes the run into the
single-row table; `fetch_sync_status` reads a row that never ran as `stale`.
The route is driven through FastAPI's own test client, and the database is a
recorder of the statements it was handed.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each status code
is the one the module's failure policy names for that input, and the stored
parameters are the made-up body's status, duration and error, in the UPDATE's
column order.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row accepts any
bearer at all, so the wrong-bearer case is answered 200.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

router_module = importlib.import_module("dashkit.core.sync.make_heartbeat_router")
from dashkit.core.sync import fetch_sync_status  # noqa: E402

TOKEN = "made-up-heartbeat-token"


class _Cursor:
    def __init__(self, conn: "_Connection") -> None:
        self.conn = conn

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.conn.sent.append((" ".join(sql.split()), params))

    def fetchone(self) -> tuple:
        return (None, None, None, None)


class _Connection:
    def __init__(self) -> None:
        self.sent: list = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


CASES = [
    pytest.param("", f"Bearer {TOKEN}", {"status": "ok", "duration_ms": 5}, (503, None), id="no-token-configured"),
    pytest.param(TOKEN, "Bearer guessed", {"status": "ok", "duration_ms": 5}, (401, None), id="a-wrong-bearer"),
    pytest.param(TOKEN, f"Bearer {TOKEN}", {"status": "maybe", "duration_ms": 5}, (400, None), id="an-unknown-status"),
    pytest.param(
        TOKEN, f"Bearer {TOKEN}", {"status": "fail", "duration_ms": 1234, "error": "disk full"},
        (200, ("fail", 1234, "disk full")), id="a-good-report-is-stored",
    ),
    pytest.param(None, None, None, {"status": "stale", "last_run_at": None}, id="a-job-that-never-ran-reads-stale"),
]


@pytest.mark.parametrize("token, bearer, body, expected", CASES)
def test_a_heartbeat_lands_only_with_the_right_bearer_and_a_known_status_and_a_never_run_job_reads_stale(
        token: str | None, bearer: str | None, body: dict | None, expected: object,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """(status code, stored run) or the read payload is the one the failure policy names."""
    conn = _Connection()
    if body is None:
        assert fetch_sync_status(conn, "backup_sync_status") == expected
        return
    monkeypatch.setenv("BACKUP_HEARTBEAT_TOKEN", token)
    monkeypatch.setattr(router_module, "get_db", lambda: conn)
    app = FastAPI()
    app.include_router(router_module.make_heartbeat_router(
        table_name="backup_sync_status", token_env_var="BACKUP_HEARTBEAT_TOKEN",
    ))
    response = TestClient(app).post("/api/internal/sync-heartbeat", json=body, headers={"Authorization": bearer})
    updates = [params[1:] for sql, params in conn.sent if sql.startswith("UPDATE")]
    assert (response.status_code, updates[0] if updates else None) == expected
