"""Read-only SQL tool: a single SELECT against the ops/dashkit Postgres.

This is the Postgres ops DB (secret-rotation tables `ops_secrets` /
`ops_secret_alerts` / `ops_secret_rotations`, the doc-edit log `ops_activity`,
and the `dashkit_*` dashboard tables), NOT openclaw's own SQLite state. There is NO pipeline
`runs`/`alerts`/`deploys` table here; run and job health live in Prometheus and
the cluster (prom_query / kubectl). The DSN comes from `OPENCLAW_DB_RO_URL`,
whose role is read-only at the Postgres level. We *also* enforce
read-only in code as defense-in-depth: the role being read-only and the
parser rejecting writes are two independent locks, plus the server-side
`SET TRANSACTION READ ONLY` is a third.

No connection pooling, one fresh connection per call, closed in `finally`.
Bounded by the LLM iteration cap (10) so RDB connection limits are safe
(see the assistant overlay (`apps/assistant/CLAUDE.md`) "No connection pooling" gotcha). Tool-module
grammar: `NAME`, `DEFINITION`, `execute`; output bounded by `text.truncate`.

FAILURE POLICY: a `psycopg2.Error` and a query the parser refuses both come
back as `result.failed` (never swallowed) so the LLM can adjust the
query. They used to be plain strings, and a plain string is coerced to OK by
`meta/result.py`, so a lookup the database had rejected counted as a read in
`chat._dispatch_tracked` and disarmed `claims.unbacked_causal_claim`: an answer
backed by nothing passed as an answer backed by a look. A failed read is not
evidence, and only the status says so. Unset DSN degrades to a "not configured"
string so the container runs before creds are wired (the seam's `REQUIRES` check
answers UNAVAILABLE before dispatch anyway).

A wrong column or table name is answered with the real columns of
the tables the query names, read from information_schema on the same
read-only connection, so the next call is right instead of a second guess.
Only columns the role holds SELECT on are listed, a table name the parser
cannot find is said to be unfound, and a lookup that fails leaves the
original failure exactly as it was.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.tools.db_query")

NAME = "db_query"

# Env var carrying the read-only DSN. Unset -> tool degrades to a clear
# "not configured" string so the container runs fine before creds are wired.
_DSN_ENV = "OPENCLAW_DB_RO_URL"
# Readiness declaration, no DSN, no tool.
REQUIRES = (_DSN_ENV,)

# Hard caps. The LIMIT is appended when the query has none; the timeout is
# a server-side guard against a runaway scan.
_ROW_LIMIT = 50
_STATEMENT_TIMEOUT_MS = 5000

# A leading SELECT or a CTE (WITH ... SELECT) is the only accepted shape.
_READ_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

# Token-level blocklist. Even though the role is read-only, reject anything
# that looks like a write/DDL/COPY so a misconfigured role can never be the
# only thing standing between the LLM and a mutation.
_FORBIDDEN_TOKENS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "copy",
    "merge",
    "call",
    "do",
    "vacuum",
    "refresh",
    "comment",
)
_TOKEN = re.compile(r"[a-zA-Z_]+")

# The column hint lists at most this many tables, and columns per table, so
# the failure text stays well inside the 8 KiB result cap.
_HINT_TABLE_LIMIT = 4
_HINT_COLUMN_LIMIT = 60

# One SQL token for the table-name parser: a quoted identifier, a bare word,
# or one punctuation character. Literals and comments are blanked first.
_SQL_TOKEN = re.compile(r'"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*|[(),.]')
_LITERAL_OR_COMMENT = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)
# Functions whose argument list uses FROM without naming a table, as in
# EXTRACT(EPOCH FROM now() - last_rotated_at).
_FROM_IN_ARGUMENT = frozenset({"extract", "substring", "trim", "overlay", "position"})
# Words that end a table reference, so they are never read as its alias.
_CLAUSE_WORDS = frozenset({
    "where", "group", "order", "limit", "offset", "having", "window", "join",
    "inner", "left", "right", "full", "cross", "natural", "on", "using",
    "union", "intersect", "except", "fetch", "for", "lateral", "tablesample",
})


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "One read-only SELECT on the ops Postgres: ops_secrets (name, "
        "max_age_days, last_rotated_at), ops_secret_alerts (secret_id, "
        "severity, resolved), ops_secret_rotations, ops_activity, and the "
        "dashkit_ dashboard tables. Runs, alerts and "
        "deploys are not here. At most 50 rows, 5 s; columns are in "
        "information_schema.columns."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "One SELECT.",
            },
        },
        "required": ["sql"],
    },
}


def _reject_reason(sql: str) -> str | None:
    """Return a rejection reason if `sql` isn't a single read statement.

    Pure string-guard; opens no connection. Returns None when the query is
    a single SELECT/WITH with no forbidden token and no statement chaining.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return "empty query"
    if ";" in stripped:
        return "multi-statement queries are not allowed"
    if not _READ_PREFIX.match(stripped):
        return "only SELECT or WITH...SELECT queries are allowed"
    lowered_tokens = {match.group(0).lower() for match in _TOKEN.finditer(stripped)}
    hit = lowered_tokens.intersection(_FORBIDDEN_TOKENS)
    if hit:
        return f"forbidden keyword(s): {', '.join(sorted(hit))}"
    return None


def _apply_limit(sql: str) -> str:
    """Append a hard LIMIT when the query has none, capping result size."""
    stripped = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\b", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped} LIMIT {_ROW_LIMIT}"


def _is_name(token: str) -> bool:
    """True for a bare word or a quoted identifier, never punctuation."""
    return token[0] == '"' or token[0] == "_" or token[0].isalpha()


def _identifier(token: str) -> str:
    """Return the name Postgres resolves a token to: quoted kept, bare lowercased."""
    if token.startswith('"'):
        return token[1:-1].replace('""', '"')
    return token.lower()


def _cte_names(tokens: list[str]) -> set[str]:
    """Return the names a WITH clause defines (`name AS (`), which are not tables."""
    return {
        _identifier(tokens[position])
        for position in range(len(tokens) - 2)
        if _is_name(tokens[position])
        and tokens[position + 1].lower() == "as"
        and tokens[position + 2] == "("
    }


def _read_table_reference(
    tokens: list[str], start: int
) -> tuple[tuple[str | None, str] | None, int]:
    """Read one `[schema.]table [AS alias]` at `start`; return it and the next index.

    The reference is None when what follows is a subquery or a function
    call, neither of which is a table whose columns can be listed.
    """
    if start >= len(tokens) or not _is_name(tokens[start]):
        return None, start
    parts = [_identifier(tokens[start])]
    cursor = start + 1
    while cursor + 1 < len(tokens) and tokens[cursor] == "." and _is_name(tokens[cursor + 1]):
        parts.append(_identifier(tokens[cursor + 1]))
        cursor += 2
    if cursor < len(tokens) and tokens[cursor] == "(":
        return None, cursor
    if cursor < len(tokens) and tokens[cursor].lower() == "as":
        cursor += 2
    elif cursor < len(tokens) and _is_name(tokens[cursor]) and tokens[cursor].lower() not in _CLAUSE_WORDS:
        cursor += 1
    schema = parts[-2] if len(parts) >= 2 else None
    return (schema, parts[-1]), cursor


def _table_names(sql: str) -> list[tuple[str | None, str]]:
    """Return the `(schema, table)` pairs a query reads FROM or JOINs, in order.

    A deliberately small parser for the SELECTs the assistant writes: it follows
    FROM and JOIN, comma lists after FROM, schema qualification, quoting and
    aliases, and skips CTE names, subqueries, function calls and the FROM
    inside EXTRACT(... FROM ...). What it cannot read it leaves out.
    """
    tokens = _SQL_TOKEN.findall(_LITERAL_OR_COMMENT.sub(" ", sql))
    ctes = _cte_names(tokens)
    found: list[tuple[str | None, str]] = []
    openers: list[str] = []
    for position, token in enumerate(tokens):
        lowered = token.lower()
        if token == "(":
            openers.append(tokens[position - 1].lower() if position else "")
        elif token == ")" and openers:
            openers.pop()
        elif lowered in ("from", "join") and not (openers and openers[-1] in _FROM_IN_ARGUMENT):
            _collect_references(tokens, position + 1, lowered == "from", ctes, found)
    return found


def _collect_references(
    tokens: list[str],
    start: int,
    allows_list: bool,
    ctes: set[str],
    found: list[tuple[str | None, str]],
) -> None:
    """Append the table references after one FROM or JOIN to `found`.

    A FROM may carry a comma list (`FROM a, b`); a JOIN names one table.
    """
    cursor = start
    while True:
        reference, cursor = _read_table_reference(tokens, cursor)
        if reference is None:
            return
        if reference[1] not in ctes and reference not in found:
            found.append(reference)
        if not allows_list or cursor >= len(tokens) or tokens[cursor] != ",":
            return
        cursor += 1


def _names_something_wrong(exc: Exception) -> bool:
    """True when Postgres refused a column or table name the query used."""
    import psycopg2.errors  # noqa: PLC0415

    return isinstance(exc, (psycopg2.errors.UndefinedColumn, psycopg2.errors.UndefinedTable))


def _readable_columns(
    connection: Any, tables: list[tuple[str | None, str]]
) -> dict[tuple[str, str], list[str]]:
    """Return `{(schema, table): [column, ...]}` the role may SELECT, for `tables`.

    Runs on the caller's connection after rolling back its aborted
    transaction, read-only and under the same timeout. information_schema
    already hides what the role holds no privilege on, and
    `has_column_privilege` narrows that to SELECT, so a table the role cannot
    read lists nothing.
    """
    connection.rollback()
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
        cursor.execute(
            "SELECT table_schema, table_name, column_name"
            " FROM information_schema.columns"
            " WHERE table_name = ANY(%s)"
            " AND has_column_privilege("
            "format('%%I.%%I', table_schema, table_name), column_name, 'SELECT')"
            " ORDER BY table_schema, table_name, ordinal_position",
            ([table for _schema, table in tables],),
        )
        rows = cursor.fetchall()
    columns: dict[tuple[str, str], list[str]] = {}
    for schema, table, column in rows:
        columns.setdefault((schema, table), []).append(column)
    return columns


def _column_hint(
    tables: list[tuple[str | None, str]], columns: dict[tuple[str, str], list[str]]
) -> str:
    """Render the real columns of each named table, or say a name was not found."""
    if not tables:
        return (
            "No table name could be read from this query, so no columns are "
            "listed; information_schema.columns has them."
        )
    lines = ["Real columns, from information_schema:"]
    for schema, table in tables[:_HINT_TABLE_LIMIT]:
        matches = [
            (found_schema, names)
            for (found_schema, found_table), names in columns.items()
            if found_table == table and (schema is None or found_schema == schema)
        ]
        if not matches:
            label = f"{schema}.{table}" if schema else table
            lines.append(f"- {label}: no table this role can read has that name")
        for found_schema, names in matches:
            label = table if found_schema == "public" else f"{found_schema}.{table}"
            shown = ", ".join(names[:_HINT_COLUMN_LIMIT])
            hidden = len(names) - _HINT_COLUMN_LIMIT
            lines.append(f"- {label}: {shown}" + (f" (+{hidden} more)" if hidden > 0 else ""))
    return "\n".join(lines)


def _wrong_name_hint(connection: Any, sql: str) -> str | None:
    """Return the column hint for a query that used a wrong column or table name.

    None when the lookup itself fails: the caller then returns the original
    failure unchanged, so a broken hint never hides or replaces the fault.
    """
    import psycopg2  # noqa: PLC0415

    tables = _table_names(sql)
    if not tables:
        return _column_hint(tables, {})
    try:
        return _column_hint(tables, _readable_columns(connection, tables))
    except psycopg2.Error as exc:
        log.warning("db_query column lookup failed: %s", exc)
        return None


def _format_rows(columns: list[str], rows: list[tuple]) -> str:
    """Render rows as compact tab-separated text with a header line."""
    if not rows:
        return f"({' | '.join(columns)})\n0 rows"
    header = " | ".join(columns)
    body = "\n".join("\t".join(str(cell) for cell in row) for row in rows)
    return f"{header}\n{body}\n({len(rows)} rows)"


def execute(tool_input: dict[str, Any]) -> "result.ToolResult | str":
    dsn = os.environ.get(_DSN_ENV, "")
    if not dsn:
        return "db_query tool not configured (OPENCLAW_DB_RO_URL unset)"

    # Lazy driver dep (module standard §3): the package must import, and the
    # registry seam must build, without psycopg2 installed; only an actual
    # query needs it.
    import psycopg2  # noqa: PLC0415

    raw_sql = str(tool_input.get("sql", ""))
    reason = _reject_reason(raw_sql)
    if reason is not None:
        return result.failed(NAME, f"query rejected: {reason}")

    bounded_sql = _apply_limit(raw_sql)

    connection = None
    try:
        connection = psycopg2.connect(dsn, connect_timeout=5)
        with connection.cursor() as cursor:
            # Server-side read-only transaction + statement timeout: the
            # third independent lock alongside the role and the parser.
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
            cursor.execute(bounded_sql)
            columns = [description[0] for description in cursor.description or []]
            rows = cursor.fetchmany(_ROW_LIMIT)
        return truncate(_format_rows(columns, rows))
    except psycopg2.Error as exc:
        # Propagate as a FAILED result, never swallow. The LLM reads
        # it and can adjust the query or give up, and the status keeps the
        # receipts counters from reading a rejected lookup as a look taken.
        log.warning("db_query failed: %s", exc)
        message = f"{type(exc).__name__}: {str(exc).strip()}"
        if connection is not None and _names_something_wrong(exc):
            hint = _wrong_name_hint(connection, raw_sql)
            if hint is not None:
                message = truncate(f"{message}\n{hint}")
        return result.failed(NAME, message)
    finally:
        if connection is not None:
            connection.close()
