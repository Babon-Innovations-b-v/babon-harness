"""An activity row records who did what, and a read returns newest first within its bounds.

WHAT IT PINS. `dashkit.core.audit`: `log_activity` writes one row, names an
unnamed user `anonymous` and stores the detail as JSON; `fetch_activity` asks
for newest first and clamps the limit to between 1 and 500. A table name that
is not a safe identifier is refused before any SQL is sent. The database is a
recorder of the statements and parameters it was handed.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each expected
parameter tuple is written out from the made-up call: the action, the user or
`anonymous`, the path, the section and the detail as `json.dumps` writes it.
The clamp is the module's stated bound: 0 becomes 1 and 9,000 becomes 500.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops the
clamp, so both bound cases fail.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from dashkit.core.audit import fetch_activity, log_activity


class _Cursor:
    def __init__(self, sent: list) -> None:
        self.sent = sent

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.sent.append((" ".join(sql.split()), params))

    def fetchall(self) -> list:
        return []


class _Connection:
    def __init__(self) -> None:
        self.sent: list = []
        self.commits = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self.sent)

    def commit(self) -> None:
        self.commits += 1


def _inserted(conn: _Connection) -> tuple:
    return [params for sql, params in conn.sent if sql.startswith("INSERT")][-1]


def _read_limit(conn: _Connection) -> tuple:
    return [params for sql, params in conn.sent if "ORDER BY created_at DESC LIMIT" in sql][-1]


def _refused(conn: _Connection, table: str) -> tuple:
    """The refusal a read of `table` raises, and what reached the database before it."""
    try:
        fetch_activity(conn, table)
    except ValueError as refusal:
        return type(refusal).__name__, conn.sent
    return "accepted", conn.sent


CASES = [
    pytest.param(
        lambda conn: (log_activity(conn, "notulen_activity", "edit", "sam", "minutes/a.md", "s2", {"words": 3}),
                      _inserted(conn))[1],
        ("edit", "sam", "minutes/a.md", "s2", '{"words": 3}'),
        id="who-did-what-where",
    ),
    pytest.param(
        lambda conn: (log_activity(conn, "notulen_activity", "view", ""), _inserted(conn))[1],
        ("view", "anonymous", None, None, None),
        id="an-unnamed-user-is-anonymous",
    ),
    pytest.param(lambda conn: (fetch_activity(conn, "notulen_activity", 0), _read_limit(conn))[1], (1,),
                 id="a-limit-below-one-reads-one"),
    pytest.param(lambda conn: (fetch_activity(conn, "notulen_activity", 9000), _read_limit(conn))[1], (500,),
                 id="a-limit-past-500-reads-500"),
    pytest.param(lambda conn: (fetch_activity(conn, "notulen_activity", 40), _read_limit(conn))[1], (40,),
                 id="a-limit-inside-the-bounds-is-kept"),
    pytest.param(lambda conn: _refused(conn, "notulen_activity; DROP TABLE x"),
                 ("ValueError", []), id="an-unsafe-table-name-sends-no-sql"),
]


@pytest.mark.parametrize("act, expected", CASES)
def test_an_activity_row_records_who_did_what_and_a_read_returns_newest_first_within_its_bounds(
        act, expected: object) -> None:
    """What reached the database is the hand-written statement parameters."""
    conn = _Connection()
    assert act(conn) == expected
