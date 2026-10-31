"""Send one deploy alert to the assistant's notify webhook, so it reaches a person.

    python3 infra/auto-deploy/notify.py <subject> <body> [key=value ...]

The deploy system pages through the assistant (apps/assistant), which owns the
owner's Signal number and decides how a page is worded and when it is sent. The
contract is the assistant's own `/webhook/notify`: a JSON body of `subject`,
`body`, `source` and an optional `facts` object, with the bearer
OPENCLAW_WEBHOOK_SECRET.

Where it is sent: ALERT_NOTIFY_URL when set, otherwise the assistant on this
box at http://127.0.0.1:OPENCLAW_PORT. Both come from the environment the
caller loaded (config/harness.env and the vault cache).

FAILURE POLICY: never raises and always exits 0. A deploy that could not page
is still a deploy, and the caller has already written the alert to its log. A
box with no assistant configured prints one line saying so.

Standard library only: it runs under the machine's system python3.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def notify_url() -> str:
    """Where the page goes, or an empty string when nothing is configured."""
    explicit = os.environ.get("ALERT_NOTIFY_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("OPENCLAW_PORT", "").strip()
    if port:
        return f"http://127.0.0.1:{port}"
    return ""


def payload(subject: str, body: str, marks: list[str]) -> dict:
    """The notify body. `facts` appears only when the sender marked something."""
    notification: dict = {"subject": subject, "body": body, "source": "auto-deploy"}
    facts = {}
    for mark in marks:
        key, _, value = mark.partition("=")
        if key and value:
            facts[key.replace("-", "_")] = value
    if facts:
        notification["facts"] = facts
    return notification


def send(subject: str, body: str, marks: list[str]) -> str:
    """Post one page. Returns a one-line account of what happened."""
    base = notify_url()
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
    if not base or not secret:
        return "notify: no assistant configured (OPENCLAW_PORT or ALERT_NOTIFY_URL, and OPENCLAW_WEBHOOK_SECRET); logged only"
    request = urllib.request.Request(
        f"{base}/webhook/notify",
        data=json.dumps(payload(subject, body, marks)).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return f"notify: sent ({response.status})"
    except urllib.error.HTTPError as failure:
        return f"notify: the assistant refused the page (HTTP {failure.code})"
    except (urllib.error.URLError, OSError) as failure:
        return f"notify: the assistant could not be reached ({failure})"


def main(argv: list[str]) -> int:
    """Send the page named on the command line; always exit 0."""
    if len(argv) < 2:
        print("usage: notify.py <subject> <body> [key=value ...]", file=sys.stderr)
        return 0
    print(send(argv[0], argv[1], argv[2:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
