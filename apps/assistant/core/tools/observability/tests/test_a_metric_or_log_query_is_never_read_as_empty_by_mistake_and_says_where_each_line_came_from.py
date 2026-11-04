"""A metric or log query is never read as empty by mistake: an unknown metric says so, a wrong guess is pointed at the metric sharing its subject, and a log line says which box and container it came from.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A metric name Prometheus does not know is refused, never read as empty.

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

A log query reads Loki and says which box and container each line came from.

WHAT IT PINS. `loki_query.execute`, at its public seam, with Loki's HTTP read
answered by a stand-in: the query goes to `LOKI_URL`, each line is labelled
`host/container` (or `host/source`), and an unset endpoint is a configuration
answer naming the variable, never an empty one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The two streams
below carry the labels a log shipper writes; the label each line must carry
is read off them by eye.

A wrong metric guess is pointed at the real metric that shares its subject.

WHAT IT PINS. `prom_query._unknown_names_refusal`, the text a guessed metric
name is refused with: the hint names the real metric that shares the guess's
distinctive words before names that are only spelled alike. Otherwise a
guess such as ops_alert_drill_age_days would be offered only
ops_secret_age_days and ops_secret_max_age_days, and the drill metric would
go unread.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The known names
are a small set Prometheus could hold, and the real drill metric is read from
the drill's own configuration (`delivery_drill._config.METRIC_NAME`). Its
difflib ratio against the guess is 0.47, under the 0.5 cutoff, which is why a
spelling-only hint cannot name it; it shares "alert" and "drill" with the
guess, which is what a reader means by the same subject.
"""
from __future__ import annotations

import inspect


# From a metric name prometheus does not know is not read as empty.

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


def _a_metric_name_prometheus_does_not_know_is_refused_not_read_as_empty(prometheus) -> None:
    """A guessed name fails, names itself, and points at the real one."""
    prometheus["query"] = _EMPTY
    answer = prom_query.execute({"query": "max(harness_secret_age_days) > 30"})
    assert answer.status == result.FAILED
    assert "'harness_secret_age_days' does not exist" in answer.error
    assert "ops_secret_age_days" in answer.error
    assert tools.execute("prom_query", {"query": "harness_monthly_cost_eur"}).startswith("FAILED [")


def _a_known_metric_with_no_series_is_empty_and_says_it_is_not_health(prometheus) -> None:
    """A real name that matched nothing is OK, and says it is not a zero."""
    prometheus["query"] = _EMPTY
    answer = prom_query.execute({"query": 'ops_secret_age_days{job="nope"}'})
    assert answer.status == result.OK
    assert "ops_secret_age_days exist" in answer.data
    assert "not a statement about health" in answer.data


def _a_real_zero_passes_through_as_a_series(prometheus) -> None:
    """A series with value 0 is an answer, untouched."""
    prometheus["query"] = _ZERO
    answer = prom_query.execute({"query": "ops_secret_age_days"})
    assert answer.status == result.OK
    assert '"0"' in answer.data
    assert "No series matched" not in answer.data


def _label_names_and_functions_are_not_taken_for_metric_names() -> None:
    """Only the selected metrics are names; labels, functions, durations are not."""
    query = 'sum by (job) (rate(http_requests_total{code=~"5.."}[5m] offset 1h)) / ignoring(code) group_left sum(up)'
    assert prom_query.metric_names_in(query) == ["http_requests_total", "up"]

# From a vm log query reads the shippers data source and says which box and container each line came from.

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


def _a_log_query_reads_loki_and_says_which_box_and_container_each_line_came_from(
    asked,
) -> None:
    answer = loki_query.execute({"query": '{source="docker"}'})
    assert len(asked) == 1 and asked[0].startswith(f"{_LOKI}/loki/api/v1/query_range?")
    assert "[ops/harness-website-1] ModuleNotFoundError" in answer
    assert "[deploy/auto-deploy] [gate] suite passed" in answer


def _an_unset_endpoint_says_not_configured_and_names_the_variable(asked, monkeypatch) -> None:
    monkeypatch.delenv("LOKI_URL")
    answer = loki_query.execute({"query": '{source="docker"}'})
    assert answer.startswith("loki_query tool not configured")
    assert "LOKI_URL" in answer
    assert asked == []

# From a wrong metric guess is pointed at the metric sharing its subject.

_DRILL_METRIC = "harness_alert_delivery_drill_last_success_timestamp_seconds"


_KNOWN_3 = frozenset(
    {
        "ops_secret_age_days",
        "ops_secret_max_age_days",
        _DRILL_METRIC,
        "up",
    }
)


def _a_wrong_metric_guess_is_pointed_at_the_metric_sharing_its_subject() -> None:
    refusal = prom_query._unknown_names_refusal(["ops_alert_drill_age_days"], _KNOWN_3)

    hint = refusal.split("Closest real names: ", 1)[1]
    assert hint.startswith(_DRILL_METRIC), refusal


def _a_guess_spelled_like_a_real_name_still_gets_it() -> None:
    refusal = prom_query._unknown_names_refusal(["ops_secret_age_day"], _KNOWN_3)

    assert "ops_secret_age_days" in refusal


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_metric_name_prometheus_does_not_know_is_refused_not_read_as_empty),
    *_cases(_a_known_metric_with_no_series_is_empty_and_says_it_is_not_health),
    *_cases(_a_real_zero_passes_through_as_a_series),
    *_cases(_label_names_and_functions_are_not_taken_for_metric_names),
    *_cases(_a_log_query_reads_loki_and_says_which_box_and_container_each_line_came_from),
    *_cases(_an_unset_endpoint_says_not_configured_and_names_the_variable),
    *_cases(_a_wrong_metric_guess_is_pointed_at_the_metric_sharing_its_subject),
    *_cases(_a_guess_spelled_like_a_real_name_still_gets_it),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_metric_or_log_query_is_never_read_as_empty_by_mistake_and_says_where_each_line_came_from(scenario, given, uses, request):
    """A metric or log query is never read as empty by mistake: an unknown metric says so, a wrong guess is pointed at the metric sharing its subject, and a log line says which box and container it came from: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
