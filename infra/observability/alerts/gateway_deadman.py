"""Gateway deadman: does the assistant's Signal gateway still answer? Runs every 60 s.

The assistant deadman watches the alert door; this one watches the OpenClaw
gateway container that holds the Signal conversation. Docker restarts a
container that dies; what nothing else sees is one that runs and no longer
answers. Probe: GET ASSISTANT_GATEWAY_HEALTH_URL (default
http://127.0.0.1:18789/healthz, the gateway published on loopback).

Three failures in a row page once, straight through signal-cli.

FAILURE POLICY: a down gateway is data, paged and exit 0, so the unit's own
failure handler does not page the same outage twice. A page that reached no
road exits 1, so `harness-notify-failure@` tries once more.
"""
from __future__ import annotations

import logging
import os
import sys
import urllib.request
from urllib.error import HTTPError, URLError

from infra.observability.alerts import deadman
from infra.observability.alerts.notify import fan_out

log = logging.getLogger("harness.gateway_deadman")

NAME = "gateway-deadman"
_DEFAULT_HEALTH_URL = "http://127.0.0.1:18789/healthz"


def health_url() -> str:
    return os.environ.get("ASSISTANT_GATEWAY_HEALTH_URL", _DEFAULT_HEALTH_URL)


def probe() -> bool:
    """True when the gateway answers its health route with a 2xx."""
    try:
        with urllib.request.urlopen(health_url(), timeout=8) as response:
            return 200 <= response.getcode() < 300
    except (HTTPError, URLError, OSError) as exc:
        log.warning("gateway probe failed: %s", exc)
        return False


def main() -> int:
    url = health_url()
    delivered = {"ok": True}

    def send(subject: str, body: str, **kwargs) -> dict[str, bool]:
        result = fan_out(subject, body, **kwargs)
        delivered["ok"] = any(result.values())
        return result

    deadman.run_cycle(
        NAME,
        healthy=probe(),
        down_message=(
            "Assistant gateway down",
            f"{url} has not answered for {deadman.FAIL_THRESHOLD} probes in a row "
            "(about three minutes). Docker restarts a dead container by itself, so "
            "this one is running and mute.\n"
            "Look: docker ps, then docker logs --tail 50 on the gateway container",
        ),
        up_message=("Assistant gateway back", f"{url} answers again."),
        send=send,
    )
    return 0 if delivered["ok"] else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
