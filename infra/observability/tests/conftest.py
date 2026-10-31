"""Make `infra.observability` importable however pytest is started, give every
test its own state directory so nothing touches /var/lib/harness, and offer a
real loopback HTTP server for tests where the network is what is under test."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """A private HARNESS_STATE_DIR and textfile directory, and no Signal config
    leaking in from the machine running the tests."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HARNESS_STATE_DIR", str(state))
    monkeypatch.setenv("HARNESS_TEXTFILE_DIR", str(state / "textfile"))
    for name in (
        "ASSISTANT_URL", "ASSISTANT_DOWN_FLAG_PATH", "OPENCLAW_WEBHOOK_SECRET",
        "SIGNAL_CLI_URL", "SIGNAL_BOT_NUMBER", "SIGNAL_RECIPIENT", "SIGNAL_ALLOWLIST",
        "MONITOR_UNIT",
    ):
        monkeypatch.delenv(name, raising=False)
    return state


class FakeServer:
    """Records every request and answers a fixed status per path (default 200)."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.requests: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                owner.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "json": json.loads(body) if body else None,
                })
                status = owner.statuses.get(self.path, 200)
                self.send_response(status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = _answer
            do_POST = _answer

            def log_message(self, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def posts_to(self, path: str) -> list[dict]:
        return [r for r in self.requests if r["method"] == "POST" and r["path"] == path]


@pytest.fixture
def fake_server():
    """Factory: `fake_server({"/path": 401})` starts a server; all are closed after."""
    servers: list[FakeServer] = []

    def start(statuses: dict[str, int] | None = None) -> FakeServer:
        server = FakeServer(statuses)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()
