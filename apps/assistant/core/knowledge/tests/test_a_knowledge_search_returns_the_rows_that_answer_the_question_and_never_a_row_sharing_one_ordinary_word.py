"""A knowledge search returns the rows that answer the question, and never a row sharing one ordinary word.

WHAT IT PINS. `core.knowledge`: `rebuild(sources=...)` fills the full-text
index and `search` answers from it, offering a row only when it carries two or
more of the question's content words, the question had one word to give, or
the row's title is the question. Stop words never count. The index lives in a
fresh state database; no disk source and no GitHub call is read.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three made-up
rows, and for each question the words each row carries are counted by hand:
"deploy gate" is in the gate row twice over; "connection pooling" shares no
whole word with the database row (no stemming); and a longer question that
shares "gate" with one row and "nightly" with another answers with neither.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row offers any
row that matched one word, so the two-rows case returns both rows.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.knowledge import index

ROWS = [
    ("bible", "deploy", "How the deploy gate works", "The deploy gate runs every commit against its own tree."),
    ("bible", "database", "Database connections", "Every service opens connections through the pool."),
    ("knowledge", "backup", "Nightly backup", "The nightly backup copies the volumes to object storage."),
]

CASES = [
    pytest.param("how does the deploy gate work", ["How the deploy gate works"], id="two-content-words-agree"),
    pytest.param("backup", ["Nightly backup"], id="a-one-word-question"),
    pytest.param("nightly gate sizing for the cluster", [], id="two-rows-each-sharing-one-word"),
    pytest.param("connection pooling", [], id="no-stemming-so-no-match"),
    pytest.param("nightly backup", ["Nightly backup"], id="the-title-is-the-question"),
]


@pytest.mark.parametrize("question, expected", CASES)
def test_a_knowledge_search_returns_the_rows_that_answer_the_question_and_never_a_row_sharing_one_ordinary_word(
        question: str, expected: list, monkeypatch: pytest.MonkeyPatch, tmp_path, frozen_clock) -> None:
    """The titles offered are the rows the hand count lets through."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    index.rebuild(sources=ROWS)
    answer = index.search(question)
    offered = [title for _source, _ref, title, _body in ROWS if f"] {title} (matched" in answer]
    assert offered == expected
