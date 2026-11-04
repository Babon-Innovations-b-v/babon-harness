"""The host-side writers produce exactly the series and targets the rules read.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

WHAT IT PINS. `node_textfile.collect.container_lines` and `unit_lines`, and
`probes.render_targets.probe_urls`, plus the metric names in
`prometheus/rules/harness.yml`: a rule reading a name no writer produces is an
alarm that can never fire.

WHERE THE EXPECTED ANSWERS COME FROM. The input is the shape `docker inspect`
and `systemctl list-units --plain --no-legend` print; the expected lines are
read off it by hand.
"""
from __future__ import annotations

import inspect
import pytest


# From the textfile collector and probe targets render what the rules read.

from pathlib import Path


from infra.observability.node_textfile import textfile
from infra.observability.node_textfile.collect import container_lines, unit_lines


from infra.observability.probes.render_targets import probe_urls


RULES = Path(__file__).resolve().parents[1] / "prometheus" / "rules" / "harness.yml"
CLUSTER_RULES = RULES.with_name("cluster.yml")


def _containers_are_published_up_and_with_their_restart_count() -> None:
    lines = container_lines([
        {"Name": "/harness-assistant-1", "State": {"Running": True}, "RestartCount": 4},
        {"Name": "/harness-notulen-1", "State": {"Running": False}, "RestartCount": 0},
    ])
    assert 'harness_container_up{name="harness-assistant-1"} 1' in lines
    assert 'harness_container_restarts_total{name="harness-assistant-1"} 4' in lines
    assert 'harness_container_up{name="harness-notulen-1"} 0' in lines


def _a_failed_unit_is_published_by_name_and_the_run_is_stamped() -> None:
    listing = (
        "harness-backup.service loaded failed failed Nightly database backup\n"
        "harness-textfile.timer loaded active waiting Run the textfile collector\n"
    )
    lines = unit_lines(listing, now=1_760_000_000.4)
    assert 'harness_systemd_unit_failed{unit="harness-backup.service"} 1' in lines
    assert 'harness_systemd_unit_failed{unit="harness-textfile.timer"} 0' in lines
    assert "harness_textfile_last_run_timestamp_seconds 1760000000" in lines


def _every_metric_the_rules_read_from_the_host_has_a_writer() -> None:
    rules = RULES.read_text()
    for name in (
        "harness_container_restarts_total",
        "harness_systemd_unit_failed",
        "harness_textfile_last_run_timestamp_seconds",
        # Written by the deploy loop, not here; the name is the contract.
        "harness_deploy_last_success_timestamp_seconds",
    ):
        assert name in rules, f"no rule reads {name}"


def _a_cluster_job_replaces_its_whole_group_on_the_pushgateway(monkeypatch, tmp_path) -> None:
    """With PUSHGATEWAY_URL set, `publish` PUTs the lines as the job's group and writes no textfile."""
    sent = []

    class _Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _urlopen(request, timeout):
        sent.append((request.get_method(), request.full_url, request.data, timeout))
        return _Answer()

    monkeypatch.setenv("HARNESS_TEXTFILE_DIR", str(tmp_path / "textfile"))
    monkeypatch.setenv("PUSHGATEWAY_URL", "http://pushgateway:9091/")
    monkeypatch.setattr(textfile.urllib.request, "urlopen", _urlopen)
    textfile.publish("signal_send", ["# TYPE m gauge", "m 7"])
    assert sent == [("PUT", "http://pushgateway:9091/metrics/job/signal_send", b"# TYPE m gauge\nm 7\n", textfile.PUSH_TIMEOUT_S)]
    assert not (tmp_path / "textfile").exists(), "a pushed job also wrote a textfile"


def _a_server_job_writes_its_textfile_when_no_pushgateway_is_named(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HARNESS_TEXTFILE_DIR", str(tmp_path / "textfile"))
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    textfile.publish("signal_send", ["m 7"])
    assert (tmp_path / "textfile" / "signal_send.prom").read_text() == "m 7\n"


def _every_pushed_series_the_cluster_rules_read_has_a_pusher() -> None:
    """The cluster rules read a pusher's freshness by its job name; a name no pusher uses never fires."""
    rules = CLUSTER_RULES.read_text()
    canary = (RULES.parents[2] / "alerts" / "signal_send_canary.py").read_text()
    outcome = (RULES.parents[3] / "auto-deploy" / "steps" / "90-outcome.sh").read_text()
    assert 'push_time_seconds{job="signal_send"}' in rules and 'publish("signal_send"' in canary
    assert "harness_deploy_last_success_timestamp_seconds" in rules
    assert "record_deploy_metric harness_deploy_last_success_timestamp_seconds" in outcome


def _probe_targets_come_from_the_domain_and_the_bare_domain_is_at() -> None:
    assert probe_urls("example.org", "@, cloud,notulen,,cloud") == [
        "https://example.org/",
        "https://cloud.example.org/",
        "https://notulen.example.org/",
    ]


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
    *_cases(_containers_are_published_up_and_with_their_restart_count),
    *_cases(_a_failed_unit_is_published_by_name_and_the_run_is_stamped),
    *_cases(_every_metric_the_rules_read_from_the_host_has_a_writer),
    *_cases(_a_cluster_job_replaces_its_whole_group_on_the_pushgateway),
    *_cases(_a_server_job_writes_its_textfile_when_no_pushgateway_is_named),
    *_cases(_every_pushed_series_the_cluster_rules_read_has_a_pusher),
    *_cases(_probe_targets_come_from_the_domain_and_the_bare_domain_is_at),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_textfile_collector_and_probe_targets_render_what_the_rules_read(scenario, given, uses, request):
    """The host-side writers produce exactly the series and targets the rules read: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
