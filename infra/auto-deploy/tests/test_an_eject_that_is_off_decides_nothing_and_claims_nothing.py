"""With the eject off, a red is answered by nothing: no claim, no clone, no push.

WHAT IT PINS. `_eject_decide` in `steps/eject_body.sh` with EJECT_ENABLED=0,
the shipped default.

WHY. The eject writes to main. Off must mean off: a dry run that still claimed
the commit's once-only slot would hand the same commit back twice the day the
eject is armed.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The body is
sourced with stub doors that record any call, a red is staged, and the
decision is run. Off means the recorder stays empty and no claim directory
exists; armed, the same staging must at least reach the preconditions, which
is what shows the stubs are wired and the first case did not pass vacuously.

WHAT IT WAS PROVED AGAINST. Defaulting EJECT_ENABLED to 1 inside the body.

GUARDS. The eject ships off.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_BODY = Path(__file__).resolve().parents[1] / "steps" / "eject_body.sh"


def _decide(tmp_path: Path, enabled: str) -> str:
    calls = tmp_path / "calls"
    calls.touch()
    stubs = "\n".join(
        f'{name}() {{ echo "{name} $*" >> "{calls}"; return 0; }}'
        for name in (
            "log", "gh_commit_author_login", "gh_email_is_not_a_person", "gh_login_for_email",
            "gh_login_is_assignable", "gh_issue_create", "gh_pull_request_create",
            "_eject_evidence_paths",
        )
    )
    script = "\n".join((
        "set -u",
        stubs,
        f'_eject_arm_preconditions_hold() {{ echo "arm $*" >> "{calls}"; eject_reason=stub; return 1; }}',
        f'STATE_DIR="{tmp_path}"',
        f'REPO="{tmp_path}"',
        f'LOG="{tmp_path}/log"',
        'GH_REPO_SLUG="owner/repo"',
        f'GATE_VERDICT_DIR="{tmp_path}"',
        f'LAST_SHA_FILE="{tmp_path}/bookmark"',
        f'. "{_BODY}"',
        'NEW_SHA="0123456789abcdef0123456789abcdef01234567"',
        'OLD_SHA="1123456789abcdef0123456789abcdef01234567"',
        "gate_red=1",
        "BOOT_FAILED_SERVICES=()",
        "BUILD_RED_SERVICES=()",
        f"EJECT_ENABLED={enabled}",
        "EJECT_DRY_RUN=0",
        f'EJECT_DECISION_LOCK="{tmp_path}/lock"',
        '_eject_decide gate-red',
        'echo "OUTCOME $eject_outcome $eject_reason" >> "$LOG"',
    ))
    subprocess.run(["bash", "-c", script], check=True, timeout=30, capture_output=True)
    return calls.read_text(encoding="utf-8") + (tmp_path / "log").read_text(encoding="utf-8")


def test_off_decides_nothing(tmp_path: Path) -> None:
    recorded = _decide(tmp_path, "0")
    assert "OUTCOME off eject_off" in recorded, recorded
    assert "arm " not in recorded and "gh_" not in recorded, recorded
    assert not (tmp_path / "ejected").exists(), "the off switch still claimed the commit"


def test_armed_reaches_the_preconditions(tmp_path: Path) -> None:
    recorded = _decide(tmp_path, "1")
    assert "OUTCOME declined" in recorded, recorded
