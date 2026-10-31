"""Pins which connection string dashkit uses.

DB_URL first, then DB_URL_OPS, then one assembled from the POSTGRES_*
values compose already has. No configuration means no connection, not a
crash at import.
"""
from __future__ import annotations

import pytest

from dashkit.core import db

_KEYS = ("DB_URL", "DB_URL_OPS", "POSTGRES_USER", "POSTGRES_PASSWORD",
         "POSTGRES_DB", "POSTGRES_HOST", "POSTGRES_PORT")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_db_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL", "postgresql://a@x/one")
    monkeypatch.setenv("DB_URL_OPS", "postgresql://b@y/two")
    assert db.dsn() == "postgresql://a@x/one"


def test_db_url_ops_is_second(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_URL_OPS", "postgresql://b@y/two")
    assert db.dsn() == "postgresql://b@y/two"


def test_assembled_from_postgres_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "harness")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/word")
    monkeypatch.setenv("POSTGRES_DB", "harness")
    assert db.dsn() == "postgresql://harness:p%40ss%2Fword@postgres:5432/harness"


def test_nothing_configured_means_no_connection() -> None:
    assert db.dsn() == ""
    assert db.get_db() is None
