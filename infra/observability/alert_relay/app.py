"""The relay's HTTP transport, standard library only. All decisions live in relay.py.

Routes (deploy interface; Alertmanager and the assistant deadman call them):

    POST /alerts            Alertmanager webhook. 200 when handled, 500 when a
                            forward or a send failed, so Alertmanager retries.
    GET  /healthz           liveness for the compose healthcheck.
    GET  /assistant-check   is the assistant alive and does it accept our
                            bearer; read by the host-side assistant deadman.

Run: python -m infra.observability.alert_relay.app  (listens on RELAY_PORT, default 8000)
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from infra.observability.alert_relay.assistant_door import check_assistant, forward_alerts
from infra.observability.alert_relay.assistant_gate import flag_mount_present
from infra.observability.alert_relay.deduper import Deduper
from infra.observability.alert_relay.relay import relay_payload
from infra.observability.alert_relay.upstream_status import wrap_fan_out
from infra.observability.alerts.notify import fan_out as _notify_fan_out

log = logging.getLogger("alert_relay")

_deduper = Deduper()


def _signal_direct(subject: str, body: str) -> dict[str, bool]:
    """The raw road: straight to signal-cli, never through the assistant that is down."""
    return _notify_fan_out(subject, body, signal_direct=True)


_raw_fan_out = wrap_fan_out(_signal_direct)


class _Handler(BaseHTTPRequestHandler):
    server_version = "harness-alert-relay"

    def _reply(self, status: int, answer: dict) -> None:
        data = json.dumps(answer).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if self.path == "/healthz":
            self._reply(200, {"status": "ok"})
        elif self.path == "/assistant-check":
            answer = check_assistant()
            answer["flag_mount_present"] = flag_mount_present()
            self._reply(200, answer)
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        if self.path != "/alerts":
            self._reply(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})
            return
        try:
            outcomes = relay_payload(payload, forward=forward_alerts, fan_out=_raw_fan_out, deduper=_deduper)
        except Exception as exc:  # noqa: BLE001 (answered as 500 so Alertmanager retries)
            log.error(json.dumps({"event": "relay_failed", "error": str(exc)}))
            self._reply(500, {"error": str(exc)})
            return
        routes: dict[str, int] = {}
        for outcome in outcomes:
            routes[outcome.route] = routes.get(outcome.route, 0) + 1
        log.info(json.dumps({"event": "alerts", "routes": routes}))
        self._reply(200, {"received": len(outcomes), "routes": routes})

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (stdlib signature)
        return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    port = int(os.environ.get("RELAY_PORT", "8000"))
    log.info("alert-relay listening on :%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
