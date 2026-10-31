"""A log query reads Loki and says which box and container each line came from.

WHAT IT PINS. `loki_query.execute`, at its public seam, with Loki's HTTP read
answered by a stand-in: the query goes to `LOKI_URL`, each line is labelled
`host/container` (or `host/source`), and an unset endpoint is a configuration
answer naming the variable, never an empty one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The two streams
below carry the labels a log shipper writes; the label each line must carry
is read off them by eye.
"""
from __future__ import annotations

from typing import Any

import pytest

from apps.assistant.core.tools.observability import loki_query

_LOKI = "https://logs.test"
_BODY = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"host": "ops", "source": "docker", "container": "harness-website-1"},
                "values": [["1792773763000000000", "ModuleNotFoundError: No module named 'site'"]],
            },
            {
                "stream": {"host": "deploy", "source": "auto-deploy", "filename": "/var/log/harness/auto-deploy.log"},
                "values": [["1792773764000000000", "[gate] suite passed in 62 s"]],
            },
        ],
    },
}


@pytest.fixture
def asked(monkeypatch) -> list[str]:
    """The URLs loki_query requested, answered with `_BODY`."""
    urls: list[str] = []

    def fake_get_json(url: str) -> Any:
        urls.append(url)
        return _BODY

    monkeypatch.setenv("LOKI_URL", _LOKI)
    monkeypatch.setattr(loki_query, "_get_json", fake_get_json)
    return urls


def test_a_log_query_reads_loki_and_says_which_box_and_container_each_line_came_from(
    asked,
) -> None:
    answer = loki_query.execute({"query": '{source="docker"}'})
    assert len(asked) == 1 and asked[0].startswith(f"{_LOKI}/loki/api/v1/query_range?")
    assert "[ops/harness-website-1] ModuleNotFoundError" in answer
    assert "[deploy/auto-deploy] [gate] suite passed" in answer


def test_an_unset_endpoint_says_not_configured_and_names_the_variable(asked, monkeypatch) -> None:
    monkeypatch.delenv("LOKI_URL")
    answer = loki_query.execute({"query": '{source="docker"}'})
    assert answer.startswith("loki_query tool not configured")
    assert "LOKI_URL" in answer
    assert asked == []
