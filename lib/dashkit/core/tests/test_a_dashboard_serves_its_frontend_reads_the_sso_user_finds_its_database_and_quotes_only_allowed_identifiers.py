"""A dashboard serves its frontend, reads the SSO user, finds its database in a fixed order and quotes only allowed identifiers.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Pins that a dashboard built by the factory serves dashkit's frontend
and refuses to serve anything outside it.

Pins which connection string dashkit uses.

DB_URL first, then DB_URL_OPS, then one assembled from the POSTGRES_*
values compose already has. No configuration means no connection, not a
crash at import.

Pins where a dashboard learns who is signed in.

Caddy's oauth2_auth snippet hands the identity over as Remote-User and
Remote-Email. get_user must prefer the stable account id, fall back to
the email, and never raise.

Pins the SQL identifier gate every dashkit table-name seam runs.

dashkit interpolates ``{domain}_*`` table names into DDL/DML f-strings;
this allowlist is the only thing between a caller-supplied domain and
SQL injection. Own-module test, so it may import
the private gate directly.
"""
from __future__ import annotations

import inspect


# From app factory serves the frontend.

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


def _base_css_is_served(client: TestClient) -> None:
    resp = client.get("/static/dashkit/base.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert "--color-" in resp.text


def _path_traversal_is_refused(client: TestClient) -> None:
    # Percent-encoded so the client cannot normalise the dots away; the
    # route receives "../core/db.py" and must refuse it.
    resp = client.get("/static/dashkit/..%2Fcore%2Fdb.py")
    assert resp.status_code == 404


def _no_database_degrades_to_empty_audit_log(client: TestClient) -> None:
    assert client.get("/api/audit-log").json() == {"activity": [], "total": 0}


def _heartbeat_without_token_configured_is_503(client: TestClient) -> None:
    resp = client.post("/api/internal/sync-heartbeat",
                       json={"status": "ok", "duration_ms": 1})
    assert resp.status_code == 503

# From db dsn resolution order.

from dashkit.core import db


_KEYS = ("DB_URL", "DB_URL_OPS", "POSTGRES_USER", "POSTGRES_PASSWORD",
         "POSTGRES_DB", "POSTGRES_HOST", "POSTGRES_PORT")


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def _db_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL", "postgresql://a@x/one")
    monkeypatch.setenv("DB_URL_OPS", "postgresql://b@y/two")
    assert db.dsn() == "postgresql://a@x/one"


def _db_url_ops_is_second(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL_OPS", "postgresql://b@y/two")
    assert db.dsn() == "postgresql://b@y/two"


def _assembled_from_postgres_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "harness")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/word")
    monkeypatch.setenv("POSTGRES_DB", "harness")
    assert db.dsn() == "postgresql://harness:p%40ss%2Fword@postgres:5432/harness"


def _nothing_configured_means_no_connection() -> None:
    assert db.dsn() == ""
    assert db.get_db() is None

# From get user reads the sso headers.

from dashkit.core import get_user


def _remote_user_wins_over_email() -> None:
    headers = {"Remote-User": "alice", "Remote-Email": "alice@example.com"}
    assert get_user(headers) == "alice"


def _email_used_when_user_missing() -> None:
    assert get_user({"Remote-Email": "bob@example.com"}) == "bob@example.com"


def _no_headers_is_anonymous() -> None:
    assert get_user({}) == "anonymous"
    assert get_user(None) == "anonymous"


def _blank_header_is_anonymous() -> None:
    assert get_user({"Remote-User": "   "}) == "anonymous"


def _basic_auth_header_is_not_an_identity() -> None:
    # The legacy Basic path is gone: a client-sent Authorization header
    # must not be read as a signed-in user.
    assert get_user({"Authorization": "Basic YWxpY2U6cHc="}) == "anonymous"

# From identifier allowlist.

from dashkit.core import validate_table_name


def _plain_snake_case_passes() -> None:
    validate_table_name("notulen_activity")
    validate_table_name("_private")


def _non_identifier_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_table_name(bad)


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_base_css_is_served),
    *_cases(_path_traversal_is_refused),
    *_cases(_no_database_degrades_to_empty_audit_log),
    *_cases(_heartbeat_without_token_configured_is_503),
    *_cases(_db_url_wins, uses=('_clean_env',)),
    *_cases(_db_url_ops_is_second, uses=('_clean_env',)),
    *_cases(_assembled_from_postgres_values, uses=('_clean_env',)),
    *_cases(_nothing_configured_means_no_connection, uses=('_clean_env',)),
    *_cases(_remote_user_wins_over_email),
    *_cases(_email_used_when_user_missing),
    *_cases(_no_headers_is_anonymous),
    *_cases(_blank_header_is_anonymous),
    *_cases(_basic_auth_header_is_not_an_identity),
    *_cases(_plain_snake_case_passes),
    *_cases(_non_identifier_rejected, "bad", [
    "Notulen",            # uppercase
    "1activity",          # leading digit
    "a-b",                # dash
    'x"; DROP TABLE y;',  # injection shape
    "",                   # empty
    "a b",                # whitespace
]),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_dashboard_serves_its_frontend_reads_the_sso_user_finds_its_database_and_quotes_only_allowed_identifiers(scenario, given, uses, request):
    """A dashboard serves its frontend, reads the SSO user, finds its database in a fixed order and quotes only allowed identifiers: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
