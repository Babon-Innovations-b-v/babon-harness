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


from infra.observability.node_textfile.collect import container_lines, unit_lines


from infra.observability.probes.render_targets import probe_urls


RULES = Path(__file__).resolve().parents[1] / "prometheus" / "rules" / "harness.yml"


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
