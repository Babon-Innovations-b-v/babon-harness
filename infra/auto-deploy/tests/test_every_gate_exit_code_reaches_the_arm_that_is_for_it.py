"""Each pytest exit code must reach its own arm of step 40's verdict chain.

WHAT IT PINS. The `if/elif/else` in `40-gate.sh` that turns pytest's exit code
into a verdict. Four arms: 0 is green, 1 is a regression, 2 to 5 are a tree that
could not be collected, and everything else is amber, the run that never started
or never finished.

WHY IT EXISTS. A chain is exactly the kind of thing that reads correctly and
behaves otherwise. Two easy breaks go in opposite directions: an extra check
inside the rc=0 arm that sets gate_red without stopping the arm, so a commit
gets vm/gate=success while it is held; and splitting the rc=0 arm into its own
top-level `if`, which detaches the elif arms so every GREEN commit falls into
the amber catch-all and reports "gate could not run (rc=0)".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The arms are not
asked what they do; they are RUN. The chain is extracted from the shipped file,
every helper it calls is replaced by a stub that records its arguments, and the
recorded calls are compared against what each exit code means, which is written
in the step's own header: green ships and is cached, a
regression ejects, a tree that will not collect is red, and a run that could not
finish blocks without ever being cached or called a regression. Nothing here is
compared to a value the script produced on an earlier day.

WHAT IT WAS PROVED AGAINST. Turning the `elif [ "$gate_rc" -eq 1 ]` back into a
second `if`, which is the exact regression above: rc=0 then falls through to the
`else` and the green case reports amber.

GUARDS. The fail-closed gate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_STEP = Path(__file__).resolve().parents[1] / "steps" / "40-gate.sh"

#: The line the chain opens on.
_CHAIN_OPENS = '    if [ "$gate_rc" -eq 0 ]; then'

#: Every helper the chain calls. Each becomes a stub that appends one line to
#: $CALLS, so what an arm did is a list of names rather than a side effect.
_STUBBED = (
    "record_gate_verdict",
    "gh_stage_head",
    "gh_stage_range",
    "gh_status_range",
    "fire_alert_once",
    "log",
    "_commit_subject",
    "_gate_failing_modules",
    "_gate_red_evidence",
)


def _chain() -> str:
    """The whole chain: the opening line to the `fi` that closes its last arm.

    Found by the chain's own arms rather than by counting keywords. A regex for
    the first `fi` at this indentation stops inside the first arm, which
    silently tests a quarter of the thing and passes; counting `if`/`fi` trips
    over the `case`, the `[ ... ] &&` and the command substitutions inside the
    arms. The arms themselves are unambiguous: they are the only lines in the
    file that start with four spaces and `elif [ "$gate_rc"`.
    """
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


def _run(tmp_path: Path, gate_rc: int) -> list[str]:
    """Run the shipped chain for one exit code. Returns the calls it made."""
    calls = tmp_path / "calls"
    calls.touch()
    stubs = "\n".join(
        f'{name}() {{ echo "{name} $*" >> "$CALLS"; return 0; }}' for name in _STUBBED
    )
    script = "\n".join((
        "set -u",
        f'CALLS="{calls}"',
        stubs,
        # The worker-crash arm is a different question with its own answer; here
        # it always says no, so rc=1 lands on the regression arm.
        "_gate_run_lost_a_worker() { return 1; }",
        "gate_worker_args=()",
        f"gate_rc={gate_rc}",
        "gate_ok=1",
        "gate_red=0",
        'gate_red_reason=""',
        'gate_scope="selected"',
        'NEW_SHA="0123456789abcdef0123456789abcdef01234567"',
        'OLD_SHA=""',
        f'AMBER_FILE="{tmp_path}/amber"',
        "AMBER_LIMIT=3",
        'GH_TARGET_DEPLOY="deploy"',
        # A path that is not there, so the register blocks inside the arm are
        # skipped: what they do is their own module's test, not this one's.
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
        'echo "FINAL gate_ok=$gate_ok gate_red=$gate_red reason=$gate_red_reason" >> "$CALLS"',
    ))
    subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    return calls.read_text(encoding="utf-8").splitlines()


def _final(lines: list[str]) -> str:
    final = [line for line in lines if line.startswith("FINAL ")]
    assert final, f"the chain did not reach its end: {lines}"
    return final[-1]


def test_a_suite_that_passed_records_a_green_verdict(tmp_path: Path) -> None:
    """rc=0 is the only arm that may cache a green verdict or say success."""
    lines = _run(tmp_path, 0)
    assert any(line.startswith("record_gate_verdict green") for line in lines), lines
    assert any("vm/gate success" in line for line in lines), lines
    assert "gate_red=0" in _final(lines), lines


def test_a_suite_that_failed_is_a_regression_and_ships_nothing(tmp_path: Path) -> None:
    """rc=1 with no lost worker is the one verdict the eject acts on."""
    lines = _run(tmp_path, 1)
    final = _final(lines)
    assert "gate_red=1" in final, lines
    assert "reason=regression" in final, lines
    assert not any("record_gate_verdict green" in line for line in lines), lines


@pytest.mark.parametrize(
    ("gate_rc", "reason"),
    [(2, "broken_tree"), (3, "broken_tree"), (4, "broken_tree"), (5, "no_tests_collected")],
)
def test_a_tree_that_could_not_be_collected_is_red(
    tmp_path: Path, gate_rc: int, reason: str
) -> None:
    """2 to 5 are a run that happened and said no, so red, and never green.

    It asserts the REASON, not just the flag. Amber sets the same flag, so a
    test that only looked at `gate_red` could not tell a broken tree from a
    box that ran out of memory, and would pass with the rc=5 arm broken.
    """
    lines = _run(tmp_path, gate_rc)
    final = _final(lines)
    assert "gate_red=1" in final, lines
    assert f"reason={reason}" in final, lines
    assert not any("record_gate_verdict green" in line for line in lines), lines


@pytest.mark.parametrize("gate_rc", [124, 126, 127, 137])
def test_a_run_that_never_finished_holds_without_ejecting(
    tmp_path: Path, gate_rc: int
) -> None:
    """Anything else could not start or finish: it blocks, and it never ejects.

    Amber blocks from the FIRST one, deliberately: the step's header says a gate
    that could not run must never look like a gate that passed. What makes it
    amber rather than red is that it is never cached and never reaches the word
    `regression`, the one verdict the eject acts on. Reverting somebody's commit
    because the box ran out of memory is the confusion the whole failure-tier
    scheme exists to prevent.

    This is the arm a detached chain sends every GREEN commit to.
    """
    lines = _run(tmp_path, gate_rc)
    final = _final(lines)
    assert "gate_ok=0" in final, lines
    assert "reason=regression" not in final, f"amber must never eject: {lines}"
    assert not any("record_gate_verdict green" in line for line in lines), lines


def test_a_green_run_never_lands_on_the_amber_arm(tmp_path: Path) -> None:
    """The regression itself, stated as its own case.

    Splitting the rc=0 arm into a second top-level `if` detaches the `elif`
    arms, and rc=0 then falls through to the `else`. A detached chain would
    report "gate could not run (rc=0)", which contradicts itself: rc=0 IS the
    run finishing.
    """
    lines = _run(tmp_path, 0)
    assert not any("could not run" in line for line in lines), lines
    assert not any("vm/gate error" in line for line in lines), lines
