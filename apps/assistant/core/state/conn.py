"""Connection cache + schema bootstrap for the openclaw SQLite state DB.

The shared seam of the `core.state` package: every table adapter
imports `get_connection` from here (module standard §2, a module
imported by 2+ siblings is a public seam, not private plumbing). The
clock helpers live in `utcnow_iso.py` / `today_utc.py`. Schema is
created lazily on first connect; statements are idempotent
(`IF NOT EXISTS`).

FAILURE POLICY: Tier-1 fail-loud, connect/schema errors propagate
(a pod that cannot open its volume-backed DB must crash, not limp).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

DEFAULT_DB_PATH = "/state/openclaw.db"


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        received_at     TEXT NOT NULL,
        fingerprint     TEXT NOT NULL,
        name            TEXT NOT NULL,
        severity        TEXT NOT NULL,
        status          TEXT NOT NULL,
        decision        TEXT NOT NULL,
        reason          TEXT NOT NULL,
        signal_sent_at  TEXT,
        dead_letter     INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS alerts_fingerprint_idx ON alerts (fingerprint)",
    "CREATE INDEX IF NOT EXISTS alerts_received_idx ON alerts (received_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS dedup_window (
        fingerprint    TEXT PRIMARY KEY,
        first_seen_at  TEXT NOT NULL,
        last_seen_at   TEXT NOT NULL,
        count          INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suppression (
        pattern    TEXT PRIMARY KEY,
        reason     TEXT NOT NULL,
        added_at   TEXT NOT NULL,
        added_by   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS budget_day (
        day_utc    TEXT PRIMARY KEY,
        spend_eur  REAL NOT NULL DEFAULT 0,
        calls      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_turns (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender      TEXT NOT NULL,
        role        TEXT NOT NULL,
        text        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS chat_turns_sender_idx ON chat_turns (sender, created_at)",
    """
    CREATE TABLE IF NOT EXISTS component_status (
        component         TEXT PRIMARY KEY,
        status            TEXT NOT NULL,
        last_ok_at        TEXT,
        last_checked_at   TEXT,
        consecutive_fails INTEGER NOT NULL DEFAULT 0,
        detail            TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS principles (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        text      TEXT NOT NULL,
        source    TEXT NOT NULL DEFAULT 'owner',
        added_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS journal (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        text      TEXT NOT NULL,
        person    TEXT,
        source    TEXT NOT NULL DEFAULT 'openclaw',
        added_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS journal_added_idx ON journal (added_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS weekly_compacts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start  TEXT NOT NULL,
        week_end    TEXT NOT NULL,
        text        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notify_pen (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        subject     TEXT NOT NULL,
        body        TEXT NOT NULL,
        source      TEXT NOT NULL,
        received_at TEXT NOT NULL,
        flushed_at  TEXT,
        facts       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS notify_pen_unflushed_idx ON notify_pen (flushed_at, received_at)",
    """
    CREATE TABLE IF NOT EXISTS page_hold (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        road        TEXT NOT NULL,
        subject     TEXT NOT NULL,
        text        TEXT NOT NULL,
        severity    TEXT NOT NULL DEFAULT '',
        key         TEXT NOT NULL DEFAULT '',
        held_at     TEXT NOT NULL,
        released_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS page_hold_pending_idx ON page_hold (released_at, held_at)",
    """
    CREATE TABLE IF NOT EXISTS security_events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,
        source     TEXT NOT NULL,
        detail     TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS security_events_recent_idx ON security_events (kind, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS worklist (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        kind            TEXT NOT NULL,
        title           TEXT NOT NULL,
        note            TEXT NOT NULL DEFAULT '',
        owner           TEXT NOT NULL DEFAULT 'assistant',
        status          TEXT NOT NULL DEFAULT 'open',
        last_finding    TEXT NOT NULL DEFAULT '',
        last_checked_at TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS worklist_open_idx ON worklist (status, created_at)",
    """
    CREATE TABLE IF NOT EXISTS assistant_actions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,
        target     TEXT NOT NULL,
        summary    TEXT NOT NULL DEFAULT '',
        actor      TEXT NOT NULL DEFAULT 'assistant',
        detail     TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS assistant_actions_recent_idx ON assistant_actions (created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS page_cooldown (
        key           TEXT PRIMARY KEY,
        last_paged_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS person_rules (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        person   TEXT NOT NULL,
        text     TEXT NOT NULL,
        added_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS person_rules_person_idx ON person_rules (person)",
    """
    CREATE TABLE IF NOT EXISTS report_marker (
        report_kind TEXT PRIMARY KEY,
        marked_at   TEXT NOT NULL,
        sha         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meeting_reminders (
        reminder_key TEXT PRIMARY KEY,
        reminded_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS meeting_reminders_at_idx ON meeting_reminders (reminded_at)",
    """
    CREATE TABLE IF NOT EXISTS reported_items (
        item_key          TEXT PRIMARY KEY,
        fingerprint       TEXT NOT NULL,
        first_reported_at TEXT NOT NULL,
        last_reported_at  TEXT NOT NULL,
        times_reported    INTEGER NOT NULL DEFAULT 0,
        answered_at       TEXT,
        escalated_at      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS reported_items_open_idx ON reported_items "
    "(answered_at, times_reported)",
    """
    CREATE TABLE IF NOT EXISTS filed_observations (
        subject      TEXT PRIMARY KEY,
        issue_number INTEGER NOT NULL,
        filed_at     TEXT NOT NULL,
        expires_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mute_lifts (
        subject   TEXT PRIMARY KEY,
        lifted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pod_boots (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        pod        TEXT NOT NULL,
        booted_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS pod_boots_recent_idx ON pod_boots (booted_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS message_evidence (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        loop       TEXT NOT NULL,
        recipient  TEXT NOT NULL DEFAULT '',
        text       TEXT NOT NULL DEFAULT '',
        readings   TEXT NOT NULL DEFAULT '[]',
        said_at    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS message_evidence_said_idx ON message_evidence (said_at DESC)",
    "CREATE INDEX IF NOT EXISTS message_evidence_loop_idx ON message_evidence (loop, said_at)",
)


# Columns added to a table that already exists somewhere. `CREATE TABLE IF NOT
# EXISTS` is the whole of the schema above and it does nothing at all to a table
# that is already there, so a column added to one of those statements reaches a
# fresh test database and never reaches the container's, which has held the same file
# on its state volume since the pen was built. That is the only reason this tuple exists,
# and it is deliberately not a migration framework: no ordering, no version row,
# no down direction.
#
# ADD COLUMN is the only shape allowed here. It is the one alteration SQLite
# makes without rewriting the table, and it is the one that cannot lose a row:
# the new column reads NULL on every row that predates it, which every reader
# has to handle anyway, because a sender that marks nothing writes that same
# NULL today.
_COLUMN_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    # The sender's own typed marking on one ping, as a JSON object. NULL
    # for every ping written before senders could mark anything, and for every
    # sender that still marks nothing.
    ("notify_pen", "facts", "TEXT"),
    # Why a held page was taken out of the queue without being sent:
    # its alert had resolved, or this firing episode was already paged. NULL on
    # every row that left as a message.
    ("page_hold", "dropped_because", "TEXT"),
    # The other fingerprints one held page speaks for, comma-joined:
    # alerts of one shared cause are triaged once and must all read delivered
    # when the page lands. NULL on every row written before it.
    ("page_hold", "covers", "TEXT"),
    # The worklist item ids one held page is about, comma-joined:
    # copied onto the chat turn when the page leaves, for the chat relay.
    # NULL on every row whose road knew of no item.
    ("page_hold", "worklist_items", "TEXT"),
    # A teammate's answer to an item, recorded by the door's `record_answer`
    #: a reply in the gateway's chat session reached nothing of ours
    # before, so the next brief asked the same question again. NULL on every
    # item nobody has answered.
    ("worklist", "answer", "TEXT"),
    ("worklist", "answered_by", "TEXT"),
    ("worklist", "answered_at", "TEXT"),
    # Which road a sent message left by, so the chat relay can tell a
    # send the gateway's chat session already holds from one it never saw.
    # NULL on every row written before it, and on inbound turns.
    ("chat_turns", "loop", "TEXT"),
    # The worklist item ids one sent message is about, comma-joined,
    # so the chat relay can tell the chat which item a reply answers.
    # NULL on every row whose road knew of no item, and on inbound turns.
    ("chat_turns", "worklist_items", "TEXT"),
)


_lock = threading.Lock()
_connection_for_path: dict[str, sqlite3.Connection] = {}


def _db_path() -> str:
    return os.environ.get("OPENCLAW_STATE_PATH", DEFAULT_DB_PATH)


def _ensure_column(
    cursor: sqlite3.Cursor, table: str, column: str, column_type: str
) -> None:
    """Add one column to a table that is missing it, and nothing otherwise.

    Reading `PRAGMA table_info` first is what makes this idempotent, which is
    the contract every statement in the schema above already has. Catching
    SQLite's "duplicate column name" instead would make the ordinary path an
    exception and would swallow the errors that are not that one.
    """
    present = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column in present:
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    for statement in _SCHEMA_STATEMENTS:
        cursor.execute(statement)
    for table, column, column_type in _COLUMN_ADDITIONS:
        _ensure_column(cursor, table, column, column_type)
    connection.commit()


def _close_all() -> None:
    """Drop the process-local connection cache (test hook plumbing:
    the public name is `reset_for_tests` in `reset.py`)."""
    with _lock:
        for connection in _connection_for_path.values():
            connection.close()
        _connection_for_path.clear()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a process-local SQLite connection. One per path, lazily
    created. Cross-thread access is serialised by `_lock`.
    """
    path = _db_path()
    with _lock:
        if path not in _connection_for_path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            connection = sqlite3.connect(path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            _ensure_schema(connection)
            _connection_for_path[path] = connection
        yield _connection_for_path[path]
