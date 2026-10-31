"""A ping a closed card still mutes is reported in the brief, and the mute is not lifted.

WHAT IT PINS. `core.closed_card_mutes.report`, read by the brief through the
`my_actions` door: for every filed card GitHub answers CLOSED, one line with
the subject it still mutes and what it silenced since the last brief; an open
card says nothing; GitHub is asked once for all cards, and not again inside
the cache; and the mute itself still stands afterwards.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three cards
written out by hand, shaped like real rows: #41 closed and
holding two revert pings (one spelled with the red marker the sender adds,
which the card was not filed under), #42 closed with nothing since the last
brief, #43 open with a ping of its own. GitHub's answer is the JSON a
GraphQL query with one alias per number returns. The newest #41 ping
arrived 04:12 UTC on Friday 16 October 2026, and local is UTC+2 that day,
so the line says Fri 06:12 local.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import pytest

_SINCE = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)
_REVERT = "auto-deploy: a commit was reverted on main"
_GITHUB_SAYS = {
    "data": {
        "repository": {
            "i41": {"state": "CLOSED"},
            "i42": {"state": "CLOSED"},
            "i43": {"state": "OPEN"},
        }
    }
}


@pytest.fixture()
def cards(tmp_path, monkeypatch) -> list[list[str]]:
    """The three cards, their pings, and a stand-in for `gh` that records
    every call made to it."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state
    from apps.assistant.core.state.conn import get_connection
    from apps.assistant.core.tools.gh import issue_states

    state.reset_for_tests()
    issue_states._cache.clear()
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO filed_observations (subject, issue_number, filed_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            [
                (_REVERT, 41, "2026-09-07T09:00:00+00:00", "2099-12-06T09:00:00+00:00"),
                ("nightly unit failed: harness-backup", 42, "2026-09-15T09:00:00+00:00",
                 "2099-12-14T09:00:00+00:00"),
                ("dependency scan found vulnerabilities", 43, "2026-10-01T09:00:00+00:00",
                 "2099-12-30T09:00:00+00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO notify_pen (subject, body, source, received_at, flushed_at) "
            "VALUES (?, 'body', 'notify', ?, ?)",
            [
                (_REVERT, "2026-10-15T22:40:00+00:00", "2026-10-15T22:41:00+00:00"),
                (f"\U0001f534 {_REVERT}", "2026-10-16T04:12:00+00:00", "2026-10-16T04:13:00+00:00"),
                ("dependency scan found vulnerabilities", "2026-10-16T03:00:00+00:00",
                 "2026-10-16T03:01:00+00:00"),
                (_REVERT, "2026-10-14T22:00:00+00:00", "2026-10-14T22:01:00+00:00"),
            ],
        )
        conn.commit()

    calls: list[list[str]] = []

    def fake_gh(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(_GITHUB_SAYS), "")

    monkeypatch.setattr(issue_states.subprocess, "run", fake_gh)
    return calls


def test_each_closed_card_is_one_line_and_the_open_one_is_not_named(cards) -> None:
    from apps.assistant.core import closed_card_mutes

    lines = closed_card_mutes.report(_SINCE)

    assert lines == [
        "#42 is closed and still mutes 'nightly unit failed: harness-backup' until "
        "2099-12-14; nothing silenced since the last brief.",
        f"#41 is closed and still mutes '{_REVERT}' until 2099-12-06; it silenced "
        "2 ping(s) since the last brief, the last at Fri 06:12 local.",
    ], lines


def test_github_is_asked_once_and_the_mute_still_stands(cards) -> None:
    from apps.assistant.core import closed_card_mutes, state

    closed_card_mutes.report(_SINCE)
    closed_card_mutes.report(_SINCE)

    assert len(cards) == 1, f"expected one cached GitHub call, got {len(cards)}"
    assert state.filed_issue_for(_REVERT) == 41, "reporting the card lifted its mute"


def test_the_brief_reads_it_through_my_actions(cards, monkeypatch) -> None:
    from apps.assistant.core.tools.meta import my_actions

    monkeypatch.setattr(my_actions, "_since_the_last_brief", lambda: _SINCE)

    answer = my_actions.execute({})

    assert "Muted by a card that is closed" in answer and "#41 is closed" in answer, answer
