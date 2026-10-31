"""A self-heal reset that lost git's index lock to the deploy cycle pages nobody.

WHAT IT PINS. The reset-and-decide block in `infra/webhook/trigger-deploy.sh`.
The deploy cycle's step 15 fast-forwards the same clone under its own lock,
which the listener deliberately does not take (GitHub wants an answer in
seconds). A reset that fails on the index lock lost a race to a process that is
doing the repair itself, so it is not a failure; any other failed reset is, and
must still be raised.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The shipped
block is extracted and run with a stub git printing a known message and exit
code; the expected verdict follows from the rule above.

WHAT IT WAS PROVED AGAINST. Treating every failed reset as a lost race.

GUARDS. Alerts only for what could not be fixed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "trigger-deploy.sh"
_BLOCK_RE = re.compile(r"^\s*reset_output=\$\(mktemp\).*?rm -f \"\$reset_output\"", re.MULTILINE | re.DOTALL)
_LOCK_MESSAGE = (
    "fatal: Unable to create '/srv/repo/.git/index.lock': File exists.\n\n"
    "Another git process seems to be running in this repository."
)
_OTHER_MESSAGE = "fatal: Could not reset index file to revision 'origin/main'."


def _run(tmp_path: Path, git_output: str, git_rc: int) -> tuple[str, str]:
    match = _BLOCK_RE.search(_SCRIPT.read_text(encoding="utf-8"))
    assert match, f"no reset-and-decide block found in {_SCRIPT}"
    stub = tmp_path / "git"
    stub.write_text(f"#!/bin/bash\ncat <<'GITEOF'\n{git_output}\nGITEOF\nexit {git_rc}\n", encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "webhook.log"
    log.touch()
    script = "\n".join((
        "set -u",
        f'export PATH="{tmp_path}:$PATH"',
        f'LOG="{log}"',
        'log() { echo "$*" >> "$LOG"; }',
        'REPO="/tmp/does-not-matter"',
        'reset_failed=""',
        match.group(0),
        'printf "RESET_FAILED=[%s]" "$reset_failed"',
    ))
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=True)
    return log.read_text(encoding="utf-8"), done.stdout


def test_a_reset_that_lost_the_index_lock_pages_nobody(tmp_path: Path) -> None:
    log, result = _run(tmp_path, _LOCK_MESSAGE, git_rc=128)
    assert "RESET_FAILED=[]" in result
    assert "paging nobody" in log


def test_any_other_reset_failure_is_still_a_failure(tmp_path: Path) -> None:
    log, result = _run(tmp_path, _OTHER_MESSAGE, git_rc=128)
    assert "RESET_FAILED=[1]" in result
    assert "paging nobody" not in log


def test_a_reset_that_worked_is_not_a_failure(tmp_path: Path) -> None:
    log, result = _run(tmp_path, "HEAD is now at 1234567 a commit", git_rc=0)
    assert "RESET_FAILED=[]" in result
    assert "paging nobody" not in log
