"""systemd OnFailure -> Signal bridge, run by `harness-notify-failure@<unit>.service`.

Every `harness-*` unit carries `OnFailure=harness-notify-failure@%n.service`, so
a backup, a timer job or a deadman that exits non-zero sends one page with the
unit name, the failing run's last line and the journal tail, instead of
failing quietly for a week.

Identical repeats are held: the first occurrence of a (unit, failure
signature) pages, then the same signature is quiet for
FAILURE_NOTIFY_COOLDOWN_SECONDS (default 12 h). A different failure of the same
unit pages at once. The signature is taken over the lines of the run that
failed (systemd's `_SYSTEMD_INVOCATION_ID`), not over the 30-line tail: a unit
that runs every five minutes holds several runs in thirty lines, and hashing
that mix makes every cycle of one outage look new. Only the parts that change
every run are stripped before hashing (journal prefix, logging stamp, CPU
accounting line); digits inside a message stay, so `http 500` and `http 401`
are two failures.

Two units are not paged over Signal:
- the Signal send canary, because its failure means Signal cannot send; it
  tells you itself once sending works again;
- `harness-assistant*` units while the assistant deadman flag is fresh,
  because the deadman already paged that outage.

FAILURE POLICY: best-effort, end of the line. Always exits 0 so a failed page
cannot trigger more OnFailure handlers. Every probe is fail-open toward paging.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from infra.observability.alerts.deadman import state_dir
from infra.observability.alerts.notify import fan_out

log = logging.getLogger("harness.failure_notify")

JOURNAL_TAIL = 30
_DEFAULT_COOLDOWN_SECONDS = 12 * 3600
_FLAG_MAX_AGE_S = 300.0
_JOURNAL_PREFIX = re.compile(r"^\S+ \S+ \S+\[\d+\]: ")
_PYTHON_LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ ")
_CPU_TIME_LINE = re.compile(r": Consumed .+ CPU time")
_SYSTEMD_OWN_LINE = re.compile(r"^\S+ \S+ systemd\[\d+\]: ")
SIGNAL_UNDER_TEST_UNITS = frozenset({"harness-signal-send-canary.service"})
ASSISTANT_UNIT_PREFIX = "harness-assistant"


@dataclass(frozen=True)
class JournalTail:
    """The journal text, and whether reading it worked."""

    text: str
    read: bool


def _run(command: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def without_unit_description(unit: str, journal_text: str) -> str:
    """Cut the unit's Description off systemd's own Starting/Started/Failed
    lines, so a long description cannot push the failing run out of the page."""
    lifecycle = re.compile(
        r"^(\S+ \S+ systemd\[\d+\]: "
        r"(?:Starting|Started|Finished|Stopping|Stopped|Failed to start) "
        + re.escape(unit)
        + r") - .*$",
        re.MULTILINE,
    )
    return lifecycle.sub(r"\1", journal_text)


def _journal_tail(unit: str) -> JournalTail:
    result = _run(["journalctl", "-u", unit, "-n", str(JOURNAL_TAIL), "--no-pager", "--output=short-iso"])
    if result is None or result.returncode != 0:
        detail = "" if result is None else result.stderr.strip()[:200]
        return JournalTail(f"(journalctl failed: {detail})", read=False)
    return JournalTail(without_unit_description(unit, result.stdout.strip()) or "(empty journal)", read=True)


def _monitored(unit: str, name: str) -> str | None:
    """A MONITOR_* value systemd handed this handler about `unit`'s failed run."""
    if os.environ.get("MONITOR_UNIT") != unit:
        return None
    return os.environ.get(name) or None


def _shown(unit: str, prop: str) -> str | None:
    result = _run(["systemctl", "show", unit, "-p", prop, "--value"])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _still_down(unit: str) -> bool:
    """Whether `systemctl show` still describes the run that failed."""
    state = _shown(unit, "ActiveState")
    if state in ("failed", "inactive"):
        return True
    return state == "activating" and _shown(unit, "SubState") == "auto-restart"


def _was_intentionally_stopped(unit: str) -> bool:
    """True for Result=signal, a deliberate `systemctl stop`."""
    result = _monitored(unit, "MONITOR_SERVICE_RESULT")
    if result is not None:
        return result == "signal"
    return _shown(unit, "Result") == "signal"


def _exit_status(unit: str) -> int | None:
    """The failing run's exit code, or None when it cannot be established."""
    result = _monitored(unit, "MONITOR_SERVICE_RESULT")
    if result is not None:
        if result != "exit-code":
            return None
        value = _monitored(unit, "MONITOR_EXIT_STATUS") or ""
    elif _still_down(unit):
        value = _shown(unit, "ExecMainStatus") or ""
    else:
        return None
    if not value.lstrip("-").isdigit() or int(value) == 0:
        return None
    return int(value)


def _failing_run_text(unit: str) -> str | None:
    """The journal lines of the run that failed, or None when it cannot be scoped."""
    invocation = _monitored(unit, "MONITOR_INVOCATION_ID")
    if invocation is None and _still_down(unit):
        invocation = _shown(unit, "InvocationID")
    if invocation is None:
        return None
    result = _run(["journalctl", "-u", unit, "--no-pager", "--output=short-iso", f"_SYSTEMD_INVOCATION_ID={invocation}"])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def error_line(run_text: str | None) -> str | None:
    """The last line the failing run wrote itself, skipping systemd's lines."""
    if run_text is None:
        return None
    own = [
        _PYTHON_LOG_STAMP.sub("", _JOURNAL_PREFIX.sub("", line)).strip()
        for line in run_text.splitlines()
        if not _SYSTEMD_OWN_LINE.match(line)
    ]
    return next((line for line in reversed(own) if line), None)


def signature(unit: str, journal_text: str) -> str:
    """A fingerprint of this failure: stable across runs of one outage,
    different for a different failure of the same unit."""
    kept = [
        _PYTHON_LOG_STAMP.sub("", _JOURNAL_PREFIX.sub("", line))
        for line in journal_text.splitlines()
        if not _CPU_TIME_LINE.search(line)
    ]
    digest = hashlib.sha1((f"{unit}\n" + "\n".join(kept)).encode()).hexdigest()[:16]
    return f"{unit}:{digest}"


def _should_page(failure_signature: str) -> bool:
    """True when this signature was not paged within the cooldown; stamps it.
    Fail-open: any state error pages."""
    try:
        cooldown = int(os.environ.get("FAILURE_NOTIFY_COOLDOWN_SECONDS", _DEFAULT_COOLDOWN_SECONDS))
        directory = state_dir() / "failure-notify"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = directory / (hashlib.sha1(failure_signature.encode()).hexdigest() + ".stamp")
        now = time.time()
        if stamp.exists() and now - float(stamp.read_text().strip() or 0) < cooldown:
            return False
        stamp.write_text(str(now))
        return True
    except Exception as exc:  # noqa: BLE001 (never let state hide a failure)
        log.warning("failure-notify cooldown errored (%s); paging anyway", exc)
        return True


def _assistant_outage_in_progress() -> bool:
    try:
        flag = state_dir() / "assistant-down"
        return (time.time() - flag.stat().st_mtime) <= _FLAG_MAX_AGE_S
    except OSError:
        return False


def _facts(unit: str, tail: JournalTail, run_text: str | None) -> dict:
    """What this sender knows, as fields for the assistant to read."""
    facts: dict = {"runbook": [f"journalctl -u {unit} -b --no-pager"]}
    exit_code = _exit_status(unit)
    if exit_code is not None:
        facts["exit_code"] = exit_code
    line = error_line(run_text)
    if line is not None:
        facts["error_line"] = line
    if not tail.read:
        facts["qualifier"] = "the journal could not be read, so this page carries no evidence"
    return facts


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python3 -m infra.observability.alerts.systemd_failure_notify <unit>", file=sys.stderr)
        return 0
    unit = args[0]
    if _was_intentionally_stopped(unit):
        log.info("not paging %s: deliberately stopped", unit)
        return 0
    if unit in SIGNAL_UNDER_TEST_UNITS:
        log.info("not paging %s over Signal: Signal is what failed", unit)
        return 0
    if unit.startswith(ASSISTANT_UNIT_PREFIX) and _assistant_outage_in_progress():
        log.info("not paging %s: the assistant deadman already paged this outage", unit)
        return 0
    tail = _journal_tail(unit)
    run_text = _failing_run_text(unit)
    if not _should_page(signature(unit, tail.text if run_text is None else run_text)):
        log.info("not paging %s: same failure paged within the cooldown", unit)
        return 0
    facts = _facts(unit, tail, run_text)
    reason = facts.get("error_line")
    body = f"Host: {socket.gethostname()}\nUnit: {unit}\n"
    if reason:
        body += f"Reason: {reason}\n"
    body += f"\nLast {JOURNAL_TAIL} journal lines:\n\n{tail.text}"
    try:
        fan_out(f"Unit failed: {unit}", body, facts=facts)
    except Exception:  # noqa: BLE001 (end of the line)
        log.exception("fan_out failed for %s", unit)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
