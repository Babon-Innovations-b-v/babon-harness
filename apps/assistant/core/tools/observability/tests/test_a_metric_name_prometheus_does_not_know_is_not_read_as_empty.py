"""A metric name Prometheus does not know is refused, never read as empty.

WHAT IT PINS. `prom_query.execute`, the tool's public interface, on the three
answers an instant query can give that all used to look alike: a name nothing
exports (FAILED, naming the closest real names), a known name that matched no
series (OK, saying it is not a health statement and not a zero), and a real
zero (a series with value "0", passed through as it came).

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The bodies are
the shapes Prometheus's HTTP API documents for `/api/v1/query` and
`/api/v1/label/__name__/values`. The names are a typical guess: the
assistant queries `harness_secret_age_days` and `harness_monthly_cost_eur`, which
never existed, while `ops_secret_age_days` and `cloud_estimated_monthly_eur` do.
Which one is closest is read off by
eye: the same suffix under a different prefix.
"""
from __future__ import annotations

from typing import Any

import pytest

from apps.assistant.core import tools
from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.observability import prom_query

_KNOWN = ["ops_secret_age_days", "cloud_estimated_monthly_eur", "up"]
_EMPTY = {"status": "success", "data": {"resultType": "vector", "result": []}}
_ZERO = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [{"metric": {"job": "secrets-exporter"}, "value": [1759730400, "0"]}],
    },
}


@pytest.fixture
def prometheus(monkeypatch):
    """A Prometheus that knows `_KNOWN` and answers queries from `answers`."""
    answers: dict[str, Any] = {}

    def fake_get_json(url: str) -> Any:
        if url.endswith("/api/v1/label/__name__/values"):
            return {"status": "success", "data": _KNOWN}
        return answers["query"]

    monkeypatch.setenv("PROM_URL", "http://prom.test")
    monkeypatch.setattr(prom_query, "_get_json", fake_get_json)
    monkeypatch.setattr(prom_query, "_names_cache", {})
    return answers


def test_a_metric_name_prometheus_does_not_know_is_refused_not_read_as_empty(prometheus) -> None:
    """A guessed name fails, names itself, and points at the real one."""
    prometheus["query"] = _EMPTY
    answer = prom_query.execute({"query": "max(harness_secret_age_days) > 30"})
    assert answer.status == result.FAILED
    assert "'harness_secret_age_days' does not exist" in answer.error
    assert "ops_secret_age_days" in answer.error
    assert tools.execute("prom_query", {"query": "harness_monthly_cost_eur"}).startswith("FAILED [")


def test_a_known_metric_with_no_series_is_empty_and_says_it_is_not_health(prometheus) -> None:
    """A real name that matched nothing is OK, and says it is not a zero."""
    prometheus["query"] = _EMPTY
    answer = prom_query.execute({"query": 'ops_secret_age_days{job="nope"}'})
    assert answer.status == result.OK
    assert "ops_secret_age_days exist" in answer.data
    assert "not a statement about health" in answer.data


def test_a_real_zero_passes_through_as_a_series(prometheus) -> None:
    """A series with value 0 is an answer, untouched."""
    prometheus["query"] = _ZERO
    answer = prom_query.execute({"query": "ops_secret_age_days"})
    assert answer.status == result.OK
    assert '"0"' in answer.data
    assert "No series matched" not in answer.data


def test_label_names_and_functions_are_not_taken_for_metric_names() -> None:
    """Only the selected metrics are names; labels, functions, durations are not."""
    query = 'sum by (job) (rate(http_requests_total{code=~"5.."}[5m] offset 1h)) / ignoring(code) group_left sum(up)'
    assert prom_query.metric_names_in(query) == ["http_requests_total", "up"]
