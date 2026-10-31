"""The weekly compact sees the commits of its window, and is told to keep a note's hedge.

WHAT IT PINS. `compact.compact_week`, at its public seam: what reaches the
summariser holds the commits GitHub has for the window next to the journal
notes, and its instructions keep a source's hedge, copy times exactly and only
say "no resolution" after checking the commits. The window's bound reaches
GitHub as UTC with a Z (a "+00:00" in a query string is read as a space), with
a page of up to 99 commits rather than a report's 40.  

WHY IT EXISTS. A compact that sees only notes and chat can write "no
resolution recorded" for a page that a commit fixed within the hour, and can
turn a patrol's hedged "likely a billing-period reset artifact" into a flat
"(artifact, fine)".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The commit sha
is the real fix, fed through the GitHub seam `changes._run_gh`, so it must
appear in what the summariser reads.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.assistant.core import brain, compact, state

_FIX_SHA = "5e5e5e5e5e"


_ASKED: list[str] = []
_LAST_WEEK_END = (datetime.now(timezone.utc) - timedelta(days=5)).replace(microsecond=123456)


def _fake_gh(args: list[str]) -> tuple[int, str, str]:
    """GitHub as `changes` reads it: one commit on main, no issue changes."""
    if args[0] == "api":
        _ASKED.append(args[1])
        row = {"sha": _FIX_SHA, "message": "secret scan: drop the leaked test token",
               "at": "2030-01-15T09:05:00Z"}
        return 0, json.dumps(row) + "\n", ""
    return 0, "[]", ""


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    _ASKED.clear()
    # The last compact's end as compact_week stores it: isoformat(), with
    # microseconds and "+00:00" (e.g. "2030-01-11T21:00:20.123456+00:00").
    state.add_compact(week_start="", week_end=_LAST_WEEK_END.isoformat(), text="before")
    state.add_note(
        "Cost 123.45, likely a billing-period reset artifact (new billing window).",
        source="patrol",
    )
    monkeypatch.setattr(compact._changes, "_run_gh", _fake_gh)
    monkeypatch.setattr(compact.budget, "is_tripped", lambda: False)
    seen: dict = {}

    def _run(*, system, messages, tools, cap):
        seen["system"] = system
        seen["user"] = messages[0]["content"]
        reply = SimpleNamespace(content=[SimpleNamespace(type="text", text="summary")])
        return brain.LoopOutcome(status="finished", response=reply)

    monkeypatch.setattr(compact._brain, "run", _run)
    return seen


def test_the_summariser_sees_the_fix_commit(captured: dict) -> None:
    assert compact.compact_week() == "summary"
    assert _FIX_SHA in captured["user"], (
        "the commit that resolved the page never reached the summariser"
    )
    assert "likely a billing-period reset artifact" in captured["user"]


def test_the_window_bound_reaches_github_as_utc_with_a_z(captured: dict) -> None:
    """The stored week end carries "+00:00", which a query string turns into a
    space; and a week holds far more than the 40 commits a report lists."""
    compact.compact_week()
    (query,) = _ASKED
    since = query.split("since=")[1].split("&")[0]
    assert since == _LAST_WEEK_END.strftime("%Y-%m-%dT%H:%M:%SZ"), query
    assert "+" not in since
    assert "per_page=100" in query, query


def test_a_cut_commit_list_is_not_read_as_no_resolution(captured: dict) -> None:
    compact.compact_week()
    assert 'MORE EXIST or COULD NOT READ, write "not checked"' in captured["system"]


def test_the_summariser_is_told_to_keep_hedges(captured: dict) -> None:
    compact.compact_week()
    system = captured["system"]
    assert "Keep a note's hedge" in system
    assert "no resolution only after checking" in system
