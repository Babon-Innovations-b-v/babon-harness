"""One rejected commit is one alert, and never none.

WHAT IT PINS. Which arm of step 40's chain may page when the gate rejects a
commit. With the eject ARMED it takes the commit off main in the same cycle and
hands it back on a pull request whose body says more than this arm's page
could, and GitHub notifies the author directly; step 40 is then a log line.
With the eject OFF (the default) nothing else will speak, so step 40 must page.

THE DANGEROUS DIRECTION IS SILENCE, NOT NOISE, so this file asks both halves. A
change that quietened both arms would pass a test that only counted pages.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The chain is
extracted from the shipped file and RUN, with every helper replaced by a stub
that records its arguments. The expected answer is the invariant above: exactly
one voice per rejected commit, and which one depends only on whether anything
else will speak.

WHAT IT WAS PROVED AGAINST. Flipping the EJECT_ENABLED condition, so step 40
pages exactly when the eject is going to speak too.

GUARDS. One alert per event.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_STEP = Path(__file__).resolve().parents[1] / "steps" / "40-gate.sh"

#: The line the rc chain opens on, and the arms that close it. Same anchors as
#: `test_every_gate_exit_code_reaches_the_arm_that_is_for_it.py`, because it is
#: the same chain read for a different question.
_CHAIN_OPENS = '    if [ "$gate_rc" -eq 0 ]; then'

_STUBBED = (
    "record_gate_verdict",
    "gh_stage_head",
    "gh_stage_range",
    "gh_status_range",
    "fire_alert",
    "fire_alert_once",
    "log",
    "_commit_subject",
    "_gate_red_evidence",
)


def _chain() -> str:
    """The whole rc chain, opening line to the `fi` closing its last arm."""
    lines = _STEP.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line == _CHAIN_OPENS]
    assert len(starts) == 1, f"expected one gate_rc chain in {_STEP}, found {len(starts)}"
    arms = [
        index
        for index, line in enumerate(lines)
        if line.startswith('    elif [ "$gate_rc"') and index > starts[0]
    ]
    assert arms, f"the gate_rc chain in {_STEP} has no elif arms left"
    for index in range(arms[-1], len(lines)):
        if lines[index] == "    fi":
            return "\n".join(lines[starts[0]: index + 1])
    raise AssertionError(f"the gate_rc chain in {_STEP} never closes")


def _pages_for(tmp_path: Path, eject_enabled: str) -> list[str]:
    """Run the regression arm with the eject armed or not. Returns the pages."""
    calls = tmp_path / "calls"
    calls.touch()
    stubs = "\n".join(
        f'{name}() {{ echo "{name} $*" >> "$CALLS"; return 0; }}' for name in _STUBBED
    )
    script = "\n".join((
        "set -u",
        f'CALLS="{calls}"',
        stubs,
        "_gate_run_lost_a_worker() { return 1; }",
        "_gate_failing_modules() { printf 'somemodule'; }",
        "gate_worker_args=()",
        "gate_rc=1",
        "gate_ok=1",
        "gate_red=0",
        'gate_red_reason=""',
        'gate_scope="selected"',
        'NEW_SHA="0123456789abcdef0123456789abcdef01234567"',
        'OLD_SHA=""',
        f'EJECT_ENABLED="{eject_enabled}"',
        f'AMBER_FILE="{tmp_path}/amber"',
        "AMBER_LIMIT=3",
        'GH_TARGET_DEPLOY="deploy"',
        'BUILD_TREE="/nonexistent"',
        f'STATE_DIR="{tmp_path}"',
        'LOG="/dev/null"',
        "gate_range_isolated=1",
        "gate_reused=0",
        "gate_selected_count=1",
        "gate_workers=4",
        "gate_start=0",
        'gate_worker_log="/dev/null"',
        "amber_streak=0",
        'gate_scope_json="/dev/null"',
        'GATE_VERDICT_DIR="/nonexistent"',
        'BUILD_HEAD_RED_FILE="/nonexistent"',
        'GATE_VENV="/nonexistent"',
        _chain(),
    ))
    subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    return [
        line
        for line in calls.read_text(encoding="utf-8").splitlines()
        if line.startswith(("fire_alert ", "fire_alert_once "))
    ]


def test_an_armed_eject_means_the_gate_does_not_page(tmp_path: Path) -> None:
    """The eject's hand-back follows in this same cycle and says more."""
    pages = _pages_for(tmp_path, "1")
    assert pages == [], (
        "step 40 paged for a commit the eject is about to take off main and "
        f"hand back itself: {pages}"
    )


def test_a_disarmed_eject_means_the_gate_is_the_only_voice(tmp_path: Path) -> None:
    """Nothing else will speak, so this arm must.

    With the eject off the commit stays on `main` and no revert follows.
    Quietening this arm as well would turn a rejected commit into silence.
    """
    pages = _pages_for(tmp_path, "0")
    assert len(pages) == 1, (
        f"expected exactly one page with the eject off, got {pages}"
    )
    assert "gate-red" in pages[0], f"the page is not the gate's red: {pages[0]}"


@pytest.mark.parametrize("armed", ["1", "0"])
def test_the_arm_still_does_everything_else_it_did(tmp_path: Path, armed: str) -> None:
    """The switch decides the page, never the verdict or the commit status."""
    calls = tmp_path / "calls"
    _pages_for(tmp_path, armed)
    recorded = calls.read_text(encoding="utf-8")
    assert "gh_stage_head vm/gate failure" in recorded, (
        f"the red no longer reaches the commit page with EJECT_ENABLED={armed}"
    )
    assert "record_gate_verdict" in recorded, (
        f"the red no longer writes a verdict with EJECT_ENABLED={armed}"
    )
