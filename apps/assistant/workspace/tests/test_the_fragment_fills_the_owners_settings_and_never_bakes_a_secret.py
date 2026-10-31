"""The gateway fragment fills the owner's settings and never bakes a secret.

WHAT IT PINS. `workspace.fragment`: every `@NAME@` placeholder in the config
fragment and the scheduled reports is filled from the settings, every
`${NAME}` the gateway interpolates itself is left exactly as written, the
report times become cron lines on the owner's zone, the voice model appears
only when voice is on, and the Signal channel comes from the vault.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The settings
below are written by hand, so the expected name, zone and cron lines are read
off them by eye.
"""
from __future__ import annotations

import json
import re

import pytest

from apps.assistant.workspace import fragment

_ENV = {
    "ASSISTANT_NAME": "Jarvis",
    "ASSISTANT_TIMEZONE": "Europe/Berlin",
    "ASSISTANT_BRIEF_TIME": "07:30",
    "ASSISTANT_ADVISOR_TIME": "10:15",
    "DOMAIN": "example.net",
    "SIGNAL_BOT_NUMBER": "+15550100099",
    "SIGNAL_ALLOWLIST": "uuid:aaa,uuid:bbb",
    "SIGNAL_RECIPIENT": "+15550100001",
    "OPENCLAW_WEBHOOK_SECRET": "must-never-appear",
}


def test_every_placeholder_is_filled_and_no_secret_is_baked() -> None:
    rendered = json.dumps([fragment.render_config_patch(_ENV), fragment.render_automations(_ENV)])
    assert not re.search(r"@[A-Z_]+@", rendered), "a placeholder was left unfilled"
    assert "must-never-appear" not in rendered
    assert "${OPENCLAW_TOOLS_AUTHORIZATION}" in rendered, "the gateway's own variable was rewritten"


def test_the_name_zone_and_report_times_come_from_the_settings() -> None:
    patch = fragment.render_config_patch(_ENV)
    assert patch["agents"]["entries"]["main"]["name"] == "Jarvis"
    assert patch["agents"]["defaults"]["userTimezone"] == "Europe/Berlin"
    jobs = {job["declarationKey"]: job for job in fragment.render_automations(_ENV)["automations"]}
    assert jobs["harness:morning-brief"]["cron"] == "30 7 * * 1-5"
    assert jobs["harness:weekly-advisor"]["cron"] == "15 10 * * 1"
    assert {job["tz"] for job in jobs.values()} == {"Europe/Berlin"}
    assert 'requested_by \\"Jarvis\\"' in json.dumps(jobs)


def test_the_voice_model_is_only_wired_when_voice_is_on() -> None:
    assert "media" not in fragment.render_config_patch(_ENV)["tools"]
    voiced = fragment.render_config_patch({**_ENV, "ASSISTANT_VOICE": "1"})
    model = voiced["tools"]["media"]["models"][0]
    assert model["baseUrl"] == "https://transcribe.example.net/v1"


def test_the_signal_channel_comes_from_the_vault() -> None:
    signal = fragment.render_config_patch(_ENV)["channels"]["signal"]
    assert signal["account"] == "+15550100099"
    assert signal["allowFrom"] == ["uuid:aaa", "uuid:bbb"]
    assert signal["defaultTo"] == "+15550100001"
    assert "channels" not in fragment.render_config_patch({**_ENV, "SIGNAL_BOT_NUMBER": ""})


def test_a_malformed_report_time_is_refused() -> None:
    with pytest.raises(ValueError):
        fragment.render_automations({**_ENV, "ASSISTANT_BRIEF_TIME": "8am"})
