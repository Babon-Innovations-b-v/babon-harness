"""A db_query that names a wrong column comes back with the table's real columns.

WHAT IT PINS. `db_query.execute`: when Postgres refuses a column or table
name, the FAILED answer lists the columns of the tables the query names, read
from information_schema on the same read-only connection, filtered to columns
the role may SELECT. When the lookup fails too, the original failure comes
back unchanged and still FAILED; when no table name can be read from the
query, the answer says so instead of guessing. Without this, each wrong guess
costs the assistant a second call to information_schema.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The queries
are written here in the shape a model guesses a column name in. The fake connection raises psycopg2's own UndefinedColumn for
the user query and answers the information_schema read with the columns the
assistant-bible names for ops_secret_alerts (secret_id, severity, message,
resolved). The tables each query reads are plain from reading the SQL.
"""
from __future__ import annotations

from typing import Any, Self

import psycopg2
import psycopg2.errors
import pytest

from apps.assistant.core.tools.infra import db_query
from apps.assistant.core.tools.meta import result

_WRONG_COLUMN_SQL = "SELECT name, severity, opened_at, resolved_at FROM ops_secret_alerts"
_REFUSAL = 'column "name" does not exist'
_ALERT_COLUMNS = [
    ("public", "ops_secret_alerts", "id"),
    ("public", "ops_secret_alerts", "secret_id"),
    ("public", "ops_secret_alerts", "severity"),
    ("public", "ops_secret_alerts", "message"),
    ("public", "ops_secret_alerts", "resolved"),
]


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.description = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.connection.statements.append((sql, params))
        if "information_schema.columns" in sql:
            if self.connection.lookup_error is not None:
                raise self.connection.lookup_error
            return
        if sql.startswith("SET "):
            return
        raise psycopg2.errors.UndefinedColumn(_REFUSAL)

    def fetchall(self) -> list[tuple[str, str, str]]:
        return list(self.connection.schema_rows)


class _FakeConnection:
    def __init__(self, schema_rows: list[tuple[str, str, str]], lookup_error: Exception | None) -> None:
        self.schema_rows = schema_rows
        self.lookup_error = lookup_error
        self.statements: list[tuple[str, Any]] = []
        self.rolled_back = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def _run(
    monkeypatch: pytest.MonkeyPatch,
    sql: str,
    schema_rows: list[tuple[str, str, str]],
    lookup_error: Exception | None = None,
) -> tuple[result.ToolResult, _FakeConnection]:
    connection = _FakeConnection(schema_rows, lookup_error)
    monkeypatch.setenv("OPENCLAW_DB_RO_URL", "postgresql://assistant-ro@ops/ops")
    monkeypatch.setattr(psycopg2, "connect", lambda *args, **kwargs: connection)
    answer = db_query.execute({"sql": sql})
    assert isinstance(answer, result.ToolResult), "a refused query must come back typed"
    return answer, connection


def _lookups(connection: _FakeConnection) -> list[tuple[str, Any]]:
    return [(sql, params) for sql, params in connection.statements if "information_schema.columns" in sql]


def test_a_wrong_column_is_answered_with_the_real_columns_of_the_tables_the_query_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query naming a wrong column comes back FAILED, carrying ops_secret_alerts' real columns."""
    answer, connection = _run(monkeypatch, _WRONG_COLUMN_SQL, _ALERT_COLUMNS)

    assert answer.status == result.FAILED, "a refused query must never read as a look taken"
    assert _REFUSAL in answer.error, "the database's own refusal must stay in the answer"
    assert "ops_secret_alerts: id, secret_id, severity, message, resolved" in answer.error, (
        f"the answer did not list the table's real columns: {answer.error!r}"
    )
    lookups = _lookups(connection)
    assert len(lookups) == 1 and lookups[0][1] == (["ops_secret_alerts"],), (
        f"the lookup must ask for exactly the table the query named: {lookups!r}"
    )
    assert "has_column_privilege" in lookups[0][0], "only columns the role may SELECT may be listed"
    assert connection.rolled_back, "the aborted transaction must be rolled back before the lookup"


def test_the_from_inside_extract_is_not_read_as_a_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """EXTRACT(EPOCH FROM a column) and a joined alias name only the two real tables."""
    sql = (
        "SELECT s.name, EXTRACT(EPOCH FROM now() - s.last_rotated_at) / 86400 AS age"
        " FROM ops_secrets s JOIN ops_secret_alerts AS a ON a.secret_id = s.id"
        " WHERE a.resolved = false"
    )
    _answer, connection = _run(monkeypatch, sql, [])

    assert _lookups(connection)[0][1] == (["ops_secrets", "ops_secret_alerts"],)


def test_a_table_the_role_cannot_read_is_named_unfound_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A table information_schema returns nothing for is said to be unreadable."""
    answer, _connection = _run(monkeypatch, "SELECT name FROM assistant_secret_vault", [])

    assert "assistant_secret_vault: no table this role can read has that name" in answer.error


def test_a_failed_lookup_leaves_the_original_failure_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """When information_schema refuses too, the answer is the first failure, still FAILED."""
    answer, _connection = _run(
        monkeypatch, _WRONG_COLUMN_SQL, _ALERT_COLUMNS, psycopg2.OperationalError("connection lost")
    )

    assert answer.status == result.FAILED
    assert answer.error == f"UndefinedColumn: {_REFUSAL}", answer.error


def test_a_query_with_no_readable_table_name_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """A query whose only FROM is a subquery gets no guessed columns."""
    answer, connection = _run(monkeypatch, "SELECT name FROM (SELECT 1 AS one) sub", _ALERT_COLUMNS)

    assert "No table name could be read from this query" in answer.error
    assert not _lookups(connection), "nothing may be looked up for a name that was never found"
