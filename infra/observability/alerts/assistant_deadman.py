"""Assistant deadman: is the assistant serving the alert path? Runs every 60 s.

It asks the alert-relay (`{RELAY_URL}/assistant-check`), because the relay is
what hands alerts to the assistant and the check should travel the road an
alert travels. The relay answers two things: the assistant's `/health` is 2xx,
and the assistant ACCEPTS the relay's bearer on `/webhook/alertmanager`. Both
must hold. An assistant can answer `/health` while refusing every delivery
with a 401, and that state looks healthy unless the bearer is checked too. A relay that cannot be reached is a failure too: alerts would not
get through it either.

Three failures in a row write the deadman flag (`$HARNESS_STATE_DIR/
assistant-down`) and page once, straight through signal-cli. While the flag is
fresh the relay stops forwarding and sends each alert group to Signal itself.
The first healthy probe clears the flag and says so.

FAILURE POLICY: Tier 1 for itself, a systemd oneshot, so a crash is a failed
unit and `harness-notify-failure@` pages it. Probe failures are data.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

from infra.observability.alerts import deadman
from infra.observability.alerts.notify import fan_out

log = logging.getLogger("harness.assistant_deadman")

NAME = "assistant-deadman"
_DEFAULT_RELAY_URL = "http://127.0.0.1:9095"


def flag_path():
    """The flag the relay reads. Same directory as the deadman's own state."""
    return deadman.state_dir() / "assistant-down"


def probe() -> tuple[bool, str]:
    """Ask the relay about the assistant. (healthy, cause when not)."""
    url = os.environ.get("RELAY_URL", _DEFAULT_RELAY_URL).rstrip("/") + "/assistant-check"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            answer = json.loads(response.read() or b"{}")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return False, f"alert-relay did not answer ({exc})"
    if not answer.get("alive"):
        return False, f"assistant /health failed: {answer.get('detail', '')}".strip()
    if not answer.get("accepts"):
        return False, "assistant refuses the relay's bearer (401/403): check OPENCLAW_WEBHOOK_SECRET"
    return True, ""


def main() -> int:
    healthy, cause = probe()
    if not healthy:
        log.warning("assistant probe failed: %s", cause)
    name = os.environ.get("ASSISTANT_NAME", "Assistant")
    verdict = deadman.run_cycle(
        NAME,
        healthy=healthy,
        down_message=(
            f"{name} is down: alerts now come to you raw",
            f"The alert path to {name} failed {deadman.FAIL_THRESHOLD} probes in a row.\n"
            f"cause: {cause}\n"
            "Until it is back, the alert-relay sends each alert group straight to Signal.\n"
            "Look: docker compose logs --tail 50 assistant alert-relay",
        ),
        up_message=(f"{name} is back: alerts are triaged again", "The alert path answers again."),
        send=fan_out,
    )
    flag = flag_path()
    if verdict.down:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(int(time.time())))
    else:
        flag.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
