"""The dead-man's switch pages when the Watchdog heartbeat has been unseen for an
hour, then at most hourly, and reads the heartbeat time in UTC.

WHAT IT PINS. `alerts.dead_mans_switch.should_page` and `watchdog_seen_ts`, the
latter against a real loopback server answering Alertmanager's `/api/v2/alerts`.

WHERE THE EXPECTED ANSWERS COME FROM. Its docstring: threshold 3600 s, repage
3600 s, a heartbeat never seen pages. Alertmanager writes `updatedAt` in UTC
(`...Z`), so 2026-10-01T00:00:00Z is epoch 1790812800 whatever the test
machine's timezone is.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from infra.observability.alerts.dead_mans_switch import should_page, watchdog_seen_ts

HOUR = 3600


@pytest.mark.parametrize(
    ("seen_ago", "paged_ago", "expected"),
    [
        (60, None, False),         # heartbeat fresh
        (HOUR - 1, None, False),   # just under the threshold
        (HOUR, None, True),        # silent for an hour
        (3 * HOUR, 10, False),     # paged ten seconds ago: hold
        (3 * HOUR, HOUR, True),    # an hour since the last page: nag
        (None, None, True),        # never seen, never paged
        (None, 600, False),        # never seen, paged ten minutes ago
    ],
)
def test_when_it_pages(seen_ago, paged_ago, expected) -> None:
    now = 10_000_000.0
    assert should_page(
        last_seen_ts=None if seen_ago is None else now - seen_ago,
        last_paged_ts=None if paged_ago is None else now - paged_ago,
        now=now,
        silent_threshold_s=HOUR,
        repage_interval_s=HOUR,
    ) is expected


@pytest.fixture
def far_timezone(monkeypatch):
    """Run in a timezone nine hours from UTC, so a local-time read is visibly wrong."""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_heartbeat_time_is_read_from_alertmanager_in_utc(far_timezone) -> None:
    alerts = [
        {"labels": {"alertname": "DiskAlmostFull"}, "updatedAt": "2026-10-02T00:00:00.000Z"},
        {"labels": {"alertname": "Watchdog"}, "updatedAt": "2026-10-01T00:00:00.000Z"},
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(alerts).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert watchdog_seen_ts(url, "Watchdog") == 1790812800
    finally:
        server.shutdown()
        server.server_close()


def test_an_unreachable_alertmanager_reads_as_silence() -> None:
    assert watchdog_seen_ts("http://127.0.0.1:9", "Watchdog") is None
