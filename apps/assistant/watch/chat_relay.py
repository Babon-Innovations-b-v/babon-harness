"""Copy what the assistant sent from elsewhere into the gateway's chat session.

WHY. The gateway answers each person's Signal messages in that person's own
chat session, `agent:main:signal:direct:<their number>` (`session.dmScope`
"per-channel-peer" in the gateway fragment). The weekday brief and the
advisor run in isolated cron sessions, the container's pages, pen, patrol and
reminders go straight to signal-cli, and a message one person asked the assistant to
send another leaves from the asker's session, so the recipient's session never
held the question a reply answers, and a "Yes" to a question the brief asked
could be read as an answer to a days-old message about something else. Each pass
here reads the container's feed of those sends (`GET /relay/sent`, chosen in
`apps/assistant/core/sent_feed.py`) and hands each one to its recipient's session
twice. The note says it was the assistant's own message, to whom, when and from which
road, so the next reply finds its question and the assistant can see how people
answered what it said.

THE SESSION KEY is upstream's per-peer key built from the number the send went
to, which is the E.164 number the gateway keys a phone sender by. A feed from a
pod older than this field names no number, and that send goes to the shared
`agent:main:main` it used to. A recipient who has never written to the assistant since
the scope changed has no session yet: `chat.inject` refuses it as "session not
found", which counts as landed, because the queued system event still reaches
their first turn and only the transcript copy is lost.

TWO DELIVERIES, because neither does both jobs. `chat.inject` writes the note
into the stored transcript and the control UI, but upstream marks what it
writes as transcript-only and never replays it to the model, so a note can
sit as the newest turn while the model still answers an older thread. So each note is first queued as a system event on the
session (`openclaw system event --mode next-heartbeat`), which the gateway puts
as a `System:` line at the top of the next inbound turn. Heartbeat is off on
this gateway, so the queue starts no run of its own. The queue lives in
gateway memory: a note queued before a gateway restart and not yet drained by a
reply is gone for the model, and stays in the transcript.

THE CURSOR is the id of the last send delivered, in
`/var/lib/harness/openclaw-chat-relay-cursor`, written after EACH send both
deliveries took. A failed one stops the pass with the cursor on the send before it,
so the next pass retries that send and nothing is dropped. A missing cursor
starts at 0, which the feed bounds to the last 24 hours; a cursor past the
pod's newest id means the state DB was reset, and it starts again at 0.

The duplicates it can make: a delivery that landed but whose answer never came
back (the CLI timed out) is retried, and so is a queued note whose inject then
failed. Neither call takes an idempotency key, so that send is shown twice. A
send shown twice is the cheaper failure.

FAILURE POLICY: Tier-2 per pass, loud when it persists. One failed pass logs,
counts itself in `/var/lib/harness/openclaw-chat-relay-fails` and exits 0. Five
in a row (ten minutes at the timer's two-minute beat) exit non-zero, so
`harness-notify-failure@%n.service` reports a relay that has stopped, once per
signature. A pod that is not serving the feed (404: the old pod of a roll that
has not reached it yet; 502 to 504 or no answer: the container restarting) gets
fifteen (thirty minutes) instead: a deploy installs this unit on the VM minutes
before the new pod is up, and the container has its own deadman, so ten minutes of
that would page for a roll that is going fine. The sends wait in the container either way.
"""
from __future__ import annotations

from apps.assistant.watch.door import door_url

from apps.assistant.shared.zone import LOCAL_ZONE

import json
import logging
import os
import subprocess
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

log = logging.getLogger("openclaw.chat_relay")

BASE_URL = door_url()
ROUTE = "/relay/sent"
SECRET_ENV = "OPENCLAW_WEBHOOK_SECRET"
FETCH_TIMEOUT_S = 30
PAGE = 20

CONTAINER = os.environ.get("ASSISTANT_GATEWAY_CONTAINER", "").strip() or "assistant-gateway"
SHARED_SESSION_KEY = "agent:main:main"
PEER_SESSION_PREFIX = "agent:main:signal:direct:"
NO_SESSION = "session not found"
LABEL = "assistant-sent"
INJECT_TIMEOUT_S = 60

STATE_DIR = Path("/var/lib/harness")
CURSOR_FILE = "openclaw-chat-relay-cursor"
FAILS_FILE = "openclaw-chat-relay-fails"
FAILS_BEFORE_LOUD = 5
FAILS_BEFORE_LOUD_POD_NOT_SERVING = 15
POD_NOT_SERVING_STATUSES = frozenset({404, 502, 503, 504})

_LOCAL_TZ = LOCAL_ZONE

class PodNotServing(RuntimeError):
    """The container answered as a roll or restart does: no feed route yet, or no answer."""


Fetcher = Callable[[int], tuple[int, list[dict]]]
Injector = Callable[[str, str], bool]


def session_key(send: Mapping[str, object]) -> str:
    """The gateway session the send's recipient talks to the assistant in."""
    address = str(send.get("address") or "").strip().lower()
    return f"{PEER_SESSION_PREFIX}{address}" if address else SHARED_SESSION_KEY


def note(send: Mapping[str, object]) -> str:
    """The text one send is injected as: the assistant's own words, said where and when."""
    stamp = datetime.fromisoformat(str(send["sent_at"])).astimezone(_LOCAL_TZ)
    when = f"{stamp:%a} {stamp.day} {stamp:%b %H:%M}"
    return (
        f"[Sent by me to {send['recipient']} on {when}, from {send['road']}. "
        "These are my own words, sent outside this conversation, so a reply "
        "here may be answering them.]\n\n"
        f"{send['text']}"
        f"{_concerns_line(send)}"
        f"{_open_items_line(send)}"
    )


def _concerns_line(send: Mapping[str, object]) -> str:
    """The worklist item this send is about, as the call that records a reply to it, or ""."""
    items = send.get("concerns") or []
    if not items:
        return ""
    named = "; ".join(f"[{item['id']}] {item['title']}" for item in items)
    calls = " or ".join(f"record_answer with item_id {item['id']}" for item in items)
    return (
        f"\n\n[This concerns worklist item {named}. If a reply answers it, "
        f"call {calls} before you reply.]"
    )


def _open_items_line(send: Mapping[str, object]) -> str:
    """The open worklist ids a reply to this send could close, or "" when the feed named none."""
    items = send.get("open_items") or []
    if not items:
        return ""
    listed = "; ".join(f"[{item['id']}] {item['title']}" for item in items)
    return (
        f"\n\n[Open on the worklist for {send['recipient']} or me: {listed}. "
        "If a reply answers one of these, call record_answer with that item_id "
        "before you reply.]"
    )


def fetch(secret: str, after: int) -> tuple[int, list[dict]]:
    """The container's newest row id and the sends past `after`, or raise saying why not."""
    if not secret:
        raise RuntimeError(f"{SECRET_ENV} unset, cannot read {ROUTE}")
    request = urllib.request.Request(
        f"{BASE_URL}{ROUTE}?after={int(after)}&limit={PAGE}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        kind = PodNotServing if exc.code in POD_NOT_SERVING_STATUSES else RuntimeError
        raise kind(f"{ROUTE} answered HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PodNotServing(f"{ROUTE} unreachable: {exc}") from exc
    if not isinstance(payload, dict) or "sends" not in payload or "newest_id" not in payload:
        raise RuntimeError(f"{ROUTE} answered a shape with no sends in it")
    return int(payload["newest_id"]), list(payload["sends"])


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _gateway_cli(what: str, args: Sequence[str], run: Runner | None) -> subprocess.CompletedProcess | None:
    """Run one `openclaw` command inside the gateway container, or None when it did not finish."""
    argv = ["docker", "exec", CONTAINER, "openclaw", *args]
    runner = run or (lambda command: subprocess.run(
        command, capture_output=True, text=True, timeout=INJECT_TIMEOUT_S, check=False
    ))
    try:
        return runner(argv)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("%s did not finish: %s", what, exc)
        return None


def _output(finished: subprocess.CompletedProcess) -> str:
    """The tail of what a gateway command printed, for a log line or a refusal check."""
    return (finished.stdout or finished.stderr or "")[-300:]


def _exited_zero(what: str, finished: subprocess.CompletedProcess | None) -> bool:
    """Whether a gateway command finished and exited 0, logging why not."""
    if finished is None:
        return False
    if finished.returncode != 0:
        log.warning("%s exited %d: %s", what, finished.returncode, _output(finished))
        return False
    return True


def inject(key: str, text: str, run: Runner | None = None) -> bool:
    """Append `text` to session `key`'s stored transcript as an assistant note. True when it
    landed, or when the session does not exist yet and only the transcript copy is lost."""
    params = json.dumps({"sessionKey": key, "message": text, "label": LABEL})
    finished = _gateway_cli(
        "chat.inject",
        ["gateway", "call", "chat.inject", "--json", "--timeout", "20000", "--params", params],
        run,
    )
    if finished is not None and finished.returncode != 0 and NO_SESSION in _output(finished):
        log.info("%s has no session yet; the queued event carries the note to their first turn", key)
        return True
    return _exited_zero("chat.inject", finished)


def enqueue(key: str, text: str, run: Runner | None = None) -> bool:
    """Queue `text` as a system event the model reads at the top of session `key`'s next turn."""
    return _exited_zero("system event", _gateway_cli(
        "system event",
        ["system", "event", "--session-key", key, "--mode", "next-heartbeat", "--json", "--text", text],
        run,
    ))


def deliver(key: str, text: str, run: Runner | None = None) -> bool:
    """Put one note in front of the model and into the transcript. True only when both took it."""
    return enqueue(key, text, run) and inject(key, text, run)


def relay_once(cursor: int, fetcher: Fetcher, injector: Injector, save: Callable[[int], None]) -> int:
    """One pass: deliver every send past `cursor`, saving after each. Returns the
    new cursor; raises when the feed could not be read or a delivery failed."""
    newest, sends = fetcher(cursor)
    if newest < cursor:
        log.warning("cursor %d is past the pod's newest row %d; the state DB was reset, starting again", cursor, newest)
        cursor = 0
        save(cursor)
        newest, sends = fetcher(cursor)
    for send in sends:
        if not injector(session_key(send), note(send)):
            raise RuntimeError(f"send {send['id']} to {send['recipient']} was not injected; it is retried next pass")
        cursor = int(send["id"])
        save(cursor)
        log.info("relayed send %d (%s, to %s)", cursor, send["loop"], send["recipient"])
    if len(sends) < PAGE and newest > cursor:
        # Nothing relayable is left up to `newest`, so the next read starts there.
        cursor = newest
        save(cursor)
    return cursor


def _read_int(path: Path) -> int:
    """A small integer state file, or 0 when it is missing or not a number."""
    try:
        return int(path.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_int(path: Path, value: int) -> None:
    """Write a small integer state file atomically."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{value}\n")
    tmp.replace(path)


def watch(state_dir: Path = STATE_DIR, fetcher: Fetcher | None = None, injector: Injector | None = None) -> int:
    """Run one pass and return the exit code (see FAILURE POLICY)."""
    cursor_path, fails_path = state_dir / CURSOR_FILE, state_dir / FAILS_FILE
    secret = os.environ.get(SECRET_ENV, "")
    try:
        relay_once(
            _read_int(cursor_path),
            fetcher or (lambda after: fetch(secret, after)),
            injector or deliver,
            lambda value: _write_int(cursor_path, value),
        )
    except Exception as exc:  # noqa: BLE001, counted, and loud once it persists
        fails = _read_int(fails_path) + 1
        _write_int(fails_path, fails)
        log.warning("chat relay pass failed (%d in a row): %s", fails, exc)
        limit = FAILS_BEFORE_LOUD_POD_NOT_SERVING if isinstance(exc, PodNotServing) else FAILS_BEFORE_LOUD
        return 1 if fails >= limit else 0
    if fails_path.exists():
        fails_path.unlink()
    return 0
