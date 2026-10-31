"""Every numbered step is sourced exactly once, in order, after the lock.

WHAT IT PINS. The explicit source list in `auto-deploy.sh` against the step
files in `steps/`. A step missing from the list never runs and nothing says so;
a step sourced before the lock races a cycle already in flight.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The directory
listing is the oracle: every `NN-*.sh` file must appear once, in lexical order,
and `00-lock.sh` first. Files that are not steps (doors.sh, eject_body.sh,
build_verdict.sh) must never be in the list.

WHAT IT WAS PROVED AGAINST. Dropping a step from the source list.

GUARDS. The orchestrator owns ordering only.
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parents[1]


def test_the_source_list_is_the_step_directory_in_order() -> None:
    text = (_HERE / "auto-deploy.sh").read_text(encoding="utf-8")
    sourced = re.findall(r'^\. "\$AUTO_DEPLOY_DIR/steps/([^"]+)"', text, flags=re.MULTILINE)
    steps = sorted(path.name for path in (_HERE / "steps").glob("[0-9][0-9]-*.sh"))
    assert sourced == steps, f"source list {sourced} does not match the steps {steps}"
    assert sourced[0] == "00-lock.sh"
    for helper in ("doors.sh", "eject_body.sh", "build_verdict.sh"):
        assert helper not in sourced, f"{helper} is not a step and must not be sourced as one"
