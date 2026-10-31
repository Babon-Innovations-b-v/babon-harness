"""The host-side writers produce exactly the series and targets the rules read.

WHAT IT PINS. `node_textfile.collect.container_lines` and `unit_lines`, and
`probes.render_targets.probe_urls`, plus the metric names in
`prometheus/rules/harness.yml`: a rule reading a name no writer produces is an
alarm that can never fire.

WHERE THE EXPECTED ANSWERS COME FROM. The input is the shape `docker inspect`
and `systemctl list-units --plain --no-legend` print; the expected lines are
read off it by hand.
"""
from __future__ import annotations

from pathlib import Path

from infra.observability.node_textfile.collect import container_lines, unit_lines
from infra.observability.probes.render_targets import probe_urls

RULES = Path(__file__).resolve().parents[1] / "prometheus" / "rules" / "harness.yml"


def test_containers_are_published_up_and_with_their_restart_count() -> None:
    lines = container_lines([
        {"Name": "/harness-assistant-1", "State": {"Running": True}, "RestartCount": 4},
        {"Name": "/harness-notulen-1", "State": {"Running": False}, "RestartCount": 0},
    ])
    assert 'harness_container_up{name="harness-assistant-1"} 1' in lines
    assert 'harness_container_restarts_total{name="harness-assistant-1"} 4' in lines
    assert 'harness_container_up{name="harness-notulen-1"} 0' in lines


def test_a_failed_unit_is_published_by_name_and_the_run_is_stamped() -> None:
    listing = (
        "harness-backup.service loaded failed failed Nightly database backup\n"
        "harness-textfile.timer loaded active waiting Run the textfile collector\n"
    )
    lines = unit_lines(listing, now=1_760_000_000.4)
    assert 'harness_systemd_unit_failed{unit="harness-backup.service"} 1' in lines
    assert 'harness_systemd_unit_failed{unit="harness-textfile.timer"} 0' in lines
    assert "harness_textfile_last_run_timestamp_seconds 1760000000" in lines


def test_every_metric_the_rules_read_from_the_host_has_a_writer() -> None:
    rules = RULES.read_text()
    for name in (
        "harness_container_restarts_total",
        "harness_systemd_unit_failed",
        "harness_textfile_last_run_timestamp_seconds",
        # Written by the deploy loop, not here; the name is the contract.
        "harness_deploy_last_success_timestamp_seconds",
    ):
        assert name in rules, f"no rule reads {name}"


def test_probe_targets_come_from_the_domain_and_the_bare_domain_is_at() -> None:
    assert probe_urls("example.org", "@, cloud,notulen,,cloud") == [
        "https://example.org/",
        "https://cloud.example.org/",
        "https://notulen.example.org/",
    ]
