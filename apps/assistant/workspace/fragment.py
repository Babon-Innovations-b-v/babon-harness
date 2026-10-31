"""The gateway's config fragment and scheduled reports, filled from the
owner's settings.

`gateway_config_patch.json` and `gateway_automations.json` are templates. The
words between `@` signs are this repository's placeholders and are filled
here; a `${NAME}` is the gateway's own syntax, interpolated by the gateway
from its environment at run time, and is left exactly as written. The two
syntaxes are different on purpose, so a secret the gateway reads from its
environment can never be baked into a file by this renderer.

    @ASSISTANT_NAME@            ASSISTANT_NAME, default Assistant
    @ASSISTANT_TIMEZONE@        ASSISTANT_TIMEZONE, default UTC
    @ASSISTANT_TRANSCRIBE_URL@  ASSISTANT_TRANSCRIBE_URL, default
                                https://transcribe.<DOMAIN>/v1
    @OWNER_NAME@                the people registry's name for the page
                                recipient, else "the owner"
    @BRIEF_CRON@                ASSISTANT_BRIEF_TIME (HH:MM, default 08:00),
                                on weekdays
    @ADVISOR_CRON@              ASSISTANT_ADVISOR_TIME (HH:MM, default 09:00),
                                on Mondays

The voice-note model block is dropped unless ASSISTANT_VOICE=1, because a
media model the gateway cannot reach fails every voice note rather than
answering that it cannot hear.

The Signal channel is rendered from the vault when SIGNAL_BOT_NUMBER is set:
the bot number, signal-cli on the compose network, direct messages from
SIGNAL_ALLOWLIST only, groups off, and SIGNAL_RECIPIENT as the default
destination. The vault is the one place these live, so the fragment carries
them every deploy instead of a hand-edited gateway config drifting from it.

FAILURE POLICY: Tier-1 fail-loud. A malformed time raises, because a report
declared at a time nobody chose is worse than a deploy that says why it
stopped.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
from typing import Any, Mapping

_HERE = pathlib.Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"@([A-Z_]+)@")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def _cron(raw: str, default: str, days: str) -> str:
    """`HH:MM` as a cron expression on `days`."""
    match = _TIME.match((raw or "").strip() or default)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError(f"not a HH:MM time: {raw!r}")
    return f"{int(match.group(2))} {int(match.group(1))} * * {days}"


def _owner_name(env: Mapping[str, str]) -> str:
    """The name the people registry gives the page recipient."""
    from apps.assistant.core import people

    recipient = (env.get("SIGNAL_RECIPIENT") or "").strip()
    person = people.identify_by_number(recipient) if recipient else None
    return person.name if person else "the owner"


def values(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Every placeholder's value, read from `env` (default: the process env)."""
    env = os.environ if env is None else env
    domain = (env.get("DOMAIN") or "").strip() or "example.org"
    return {
        "ASSISTANT_NAME": (env.get("ASSISTANT_NAME") or "").strip() or "Assistant",
        "ASSISTANT_TIMEZONE": (env.get("ASSISTANT_TIMEZONE") or "").strip() or "UTC",
        "ASSISTANT_TRANSCRIBE_URL": (env.get("ASSISTANT_TRANSCRIBE_URL") or "").strip()
        or f"https://transcribe.{domain}/v1",
        "OWNER_NAME": _owner_name(env),
        "BRIEF_CRON": _cron(env.get("ASSISTANT_BRIEF_TIME", ""), "08:00", "1-5"),
        "ADVISOR_CRON": _cron(env.get("ASSISTANT_ADVISOR_TIME", ""), "09:00", "1"),
    }


def _fill(node: Any, filled: Mapping[str, str]) -> Any:
    if isinstance(node, str):
        return _PLACEHOLDER.sub(lambda match: filled.get(match.group(1), match.group(0)), node)
    if isinstance(node, list):
        return [_fill(item, filled) for item in node]
    if isinstance(node, dict):
        return {key: _fill(value, filled) for key, value in node.items()}
    return node


def _template(name: str) -> dict[str, Any]:
    return json.loads((_HERE / name).read_text(encoding="utf-8"))


def render_config_patch(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The gateway config fragment with every placeholder filled."""
    env = os.environ if env is None else env
    patch = _fill(_template("gateway_config_patch.json"), values(env))
    if (env.get("ASSISTANT_VOICE") or "").strip() != "1":
        patch = copy.deepcopy(patch)
        patch.get("tools", {}).pop("media", None)
    signal = _signal_channel(env)
    if signal:
        patch.setdefault("channels", {})["signal"] = signal
    return patch


def _signal_channel(env: Mapping[str, str]) -> dict[str, Any]:
    """The gateway's Signal channel from the vault, or {} without a bot number."""
    account = (env.get("SIGNAL_BOT_NUMBER") or "").strip()
    if not account:
        return {}
    allow = [item.strip() for item in (env.get("SIGNAL_ALLOWLIST") or "").split(",") if item.strip()]
    channel: dict[str, Any] = {
        "enabled": True,
        "account": account,
        "transport": {"kind": "container", "url": "http://signal-cli:8080"},
        "dmPolicy": "allowlist",
        "allowFrom": allow,
        "groupPolicy": "disabled",
    }
    recipient = (env.get("SIGNAL_RECIPIENT") or "").strip()
    if recipient:
        channel["defaultTo"] = recipient
    return channel


def render_automations(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The scheduled reports with every placeholder filled."""
    return _fill(_template("gateway_automations.json"), values(env))


__all__ = ["render_automations", "render_config_patch", "values"]
