"""The gateway fragment pins the assistant's user timezone to Europe/local.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`. With `agents.defaults.userTimezone`
unset, upstream OpenClaw resolves the host zone, which on the ops VM is UTC, and
stamps every Signal envelope, every cron "Current time:" line and the prompt's
local date in UTC. The model then has to convert to local in its head, and
gets it wrong: an hour off on a time range, or the wrong weekday for
late-evening commits.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The key path is
read off the running gateway's schema (`openclaw config schema` on OpenClaw
2026.9.1, 2026-10-06): `agents.defaults.userTimezone`, a string, and upstream's
`docs/concepts/timezone.md` in github.com/openclaw/openclaw says that one key drives envelopes, queued system
events and the prompt's date (`envelopeTimezone` was removed upstream). The
zone is where the team works, an IANA name the gateway's Intl accepts.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

from apps.assistant.shared.zone import LOCAL_ZONE_NAME




def test_the_gateway_fragment_pins_the_user_timezone() -> None:
    """Every clock the gateway shows the model is local wall-clock."""
    patch = fragment.render_config_patch()
    assert patch["agents"]["defaults"]["userTimezone"] == LOCAL_ZONE_NAME
