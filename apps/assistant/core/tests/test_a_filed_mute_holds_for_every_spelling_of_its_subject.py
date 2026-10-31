"""A filed mute holds for every spelling of its subject.

WHAT IT PINS. The filed mute across its three users: `state.record_filed`,
`state.filed_issue_for` and `state.clear_filed` (the table), the notify pen's
split of a batch into what may page and what is already on the board
(`notify_flush._split_silenced`), and the recurring filer
(`recurring_alerts.file_recurring_observations`). A subject is one mute whether
the sender put a severity marker or the product banner in front of it, and a
`must_page` marking no longer walks past a card that is on the board.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every spelling
below is the same sentence with furniture in front of it, written out by hand:
the bare text, the text after a red circle, and the text after a red circle and
"[the project] ". The answer for each is read off that: same sentence, same mute.
The filer case is a fortnight of rows written by hand, three days bare and one
day marked red, so the subject was critical in one of its spellings and must
never be filed whatever the count says.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_BARE = "auto-deploy: a commit was reverted on main"
_MARKED = "\U0001f534 " + _BARE
_BANNERED = "\U0001f534 [the project] " + _BARE


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """A fresh state file of this test's own; nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state as state_module

    return state_module


def test_a_card_filed_off_the_bare_spelling_mutes_the_marked_ping(state) -> None:
    """The an issue shape: filed bare, the next ping red and bannered, must_page set."""
    from apps.assistant.core import notify_flush

    state.record_filed(_BARE, 41)
    ping = {"id": 1, "subject": _BANNERED, "facts": {"must_page": "yes"}}

    live, silenced = notify_flush._split_silenced([ping])

    assert not live and [held["id"] for held in silenced] == [1], (
        "a ping on a filed subject paged because its sender wrote a marker, a "
        "banner or must_page in front of the same sentence"
    )


def test_a_row_stored_with_a_marker_is_found_and_lifted_by_any_spelling(state) -> None:
    """Rows written before the key existed carry the marker; they still count."""
    from apps.assistant.core.state.conn import get_connection

    later = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO filed_observations (subject, issue_number, filed_at, "
            "expires_at) VALUES (?, ?, ?, ?)",
            (_MARKED, 1, datetime.now(timezone.utc).isoformat(), later),
        )
        conn.commit()

    assert state.filed_issue_for(_BARE) == 1, "the bare lookup missed the old marked row"
    assert state.clear_filed(_BANNERED) is True, "the lift did not find the old row"
    assert state.filed_issue_for(_MARKED) is None, "the lifted mute still holds"


def test_a_subject_critical_in_one_spelling_is_never_filed(state, monkeypatch) -> None:
    """Three bare days and one red day: the red day makes it unfileable."""
    from apps.assistant.core import recurring_alerts

    today = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)
    rows = [
        {
            "name": state.batch_row_name(1, [_BARE]),
            "severity": "info",
            "received_at": (today - timedelta(days=days_ago)).isoformat(),
        }
        for days_ago in (1, 2, 3, 4)
    ]
    rows.append(
        {
            "name": state.batch_row_name(1, [_MARKED]),
            "severity": "critical",
            "received_at": (today - timedelta(days=5)).isoformat(),
        }
    )
    monkeypatch.setattr(state, "alerts_since", lambda _start, limit: rows)
    created: list[dict] = []
    monkeypatch.setattr(
        recurring_alerts.github_act,
        "execute",
        lambda payload, actor: created.append(payload) or "created #9999",
    )

    filed = recurring_alerts.file_recurring_observations()

    assert filed == [] and created == [], (
        "the bare spelling of a subject that paged red was filed and muted"
    )
