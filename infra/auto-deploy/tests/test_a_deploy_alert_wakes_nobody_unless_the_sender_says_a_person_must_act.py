"""A deploy alert is a log line unless its sender says a person must act.

WHAT IT PINS. `fire_alert` in `steps/doors.sh`, the one door every deploy alert
goes through, and `notify.py`, the page it sends.

WHY. A default that pages means every call site added later pages too, and a
page people learn to swipe away is worse than none. So the default is a record
in the deploy log, and only `--wakes-somebody` reaches the assistant.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The shipped
door is sourced into a shell whose `python3` is a stub that records its
arguments, so what was sent is read from the stub, not from the door. The
expected answer is the rule above.

WHAT IT WAS PROVED AGAINST. Sending every alert, flagged or not.

GUARDS. The alert budget.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

_DOORS = Path(__file__).resolve().parents[1] / "steps" / "doors.sh"
_NOTIFY = Path(__file__).resolve().parents[1] / "notify.py"


def _sent(tmp_path: Path, *arguments: str) -> tuple[list[str], str]:
    """Fire one alert through the shipped door. Returns (python3 argv, log)."""
    recorded = tmp_path / "argv"
    log = tmp_path / "log"
    quoted = " ".join(f"'{argument}'" for argument in arguments)
    script = "\n".join((
        "set -u",
        f'LOG="{log}"',
        'log() { echo "$*" >> "$LOG"; }',
        f'python3() {{ printf "%s\\n" "$@" > "{recorded}"; }}',
        f'. "{_DOORS}"',
        'REPO=/nonexistent',
        f"fire_alert {quoted}",
    ))
    subprocess.run(["bash", "-c", script], check=True, timeout=30, capture_output=True)
    argv = recorded.read_text(encoding="utf-8").splitlines() if recorded.exists() else []
    return argv, log.read_text(encoding="utf-8")


def test_an_unmarked_alert_is_a_record_and_sends_nothing(tmp_path: Path) -> None:
    argv, log = _sent(tmp_path, "auto-deploy: something happened", "the body")
    assert argv == [], f"an unmarked alert was sent: {argv}"
    assert "RECORD: auto-deploy: something happened" in log


def test_a_marked_alert_is_sent_with_its_markings(tmp_path: Path) -> None:
    argv, log = _sent(
        tmp_path, "auto-deploy: no room", "the body", "--blocks-deploy", "yes", "--wakes-somebody"
    )
    assert argv[1:4] == ["auto-deploy: no room", "the body", "blocks-deploy=yes"], argv
    assert "ALERT: auto-deploy: no room" in log


def test_the_page_carries_the_markings_as_facts() -> None:
    spec = importlib.util.spec_from_file_location("notify", _NOTIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.payload("s", "b", []) == {"subject": "s", "body": "b", "source": "auto-deploy"}
    assert module.payload("s", "b", ["blocks-deploy=yes"])["facts"] == {"blocks_deploy": "yes"}
