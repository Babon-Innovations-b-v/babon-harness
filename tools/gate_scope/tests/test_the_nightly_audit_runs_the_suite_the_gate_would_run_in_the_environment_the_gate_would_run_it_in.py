"""The control that licenses narrowing has to be about the thing it licenses.

WHAT IT PINS. The four ways `audit_full_run.sh` and `steps/40-gate.sh` have to
agree, because the audit's whole job is to answer whether the gate's narrowing
dropped a test that would have failed. It can only answer that if the two run
the same suite the same way: the same ignore list, the same clean environment,
the same tree, and an interpreter belonging to that tree.

WHY IT EXISTS. The audit licenses the gate to narrow. An audit that ran a
different suite, in a different tree or a different environment, is not
evidence about the gate in either direction: a green licenses narrowing it did
not check, and a red pins every cycle to the full suite until a person clears
the marker by hand. Running it in the clone instead of an export, or through the
clone's interpreter, are the two easy ways to get that wrong.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Not from either
script's own words. The `env -i` list is read out of BOTH shipped files and
compared to each other, so neither is the authority and a change to one without
the other is what fails. The ignore list is the same construction: `40-gate.sh`
is the only source, and the audit greps it rather than restating it, which the
audit's own header calls out. The interpreter is asked a structural question with
one right answer: the run's tree and its interpreter must come from the same
place, and the clone is not that place.

WHAT IS DELIBERATELY NOT PINNED. The gate may run pytest-xdist workers
(GATE_PYTEST_WORKERS) and the audit runs one process. A test that only fails
under xdist passes the audit; the audit's question is which tests the SELECTION
dropped, which running them all answers.

WHAT IT WAS PROVED AGAINST. The break points the audit's pytest back at the
clone's venv.

GUARDS. The narrowing licence.
"""
from __future__ import annotations

import re
from pathlib import Path

#: `<repo>/tools/gate_scope/tests/` is three below the root.
_REPO = Path(__file__).resolve().parents[3]
_AUDIT = _REPO / "tools/gate_scope/audit_full_run.sh"
_GATE = _REPO / "infra/auto-deploy/steps/40-gate.sh"

#: A variable set on an `env -i` line, e.g. `PYTHONPATH="$BUILD_TREE"`.
_ENV_ASSIGNMENT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _clean_environment(script: Path) -> set[str]:
    """The variables a script hands to its `env -i` pytest run.

    Read from the `env -i` line to the `timeout` that ends it, which is the
    shape both scripts write and the only place either of them uses `env -i`.
    """
    text = script.read_text(encoding="utf-8")
    blocks = []
    for start in (match.end() for match in re.finditer(r"env -i", text)):
        stop = text.find("timeout", start)
        assert stop > start, f"an `env -i` in {script.name} never reaches its run"
        blocks.append(text[start:stop])
    assert blocks, f"{script.name} does not run pytest under `env -i`"
    return {
        name
        for block in blocks
        for name in _ENV_ASSIGNMENT.findall(block)
    }


#: What the gate sets and the audit does not. Empty: anything appearing on
#: either side alone is drift, which is what this makes visible.
_GATE_ONLY: frozenset[str] = frozenset()


def test_both_runs_get_the_same_clean_environment() -> None:
    """One list, written twice, so it is compared rather than trusted.

    Both scripts say in their own comments to keep the list identical, and a
    comment cannot enforce that. Either file may be the one that moved: the
    assertion names neither as the authority.
    """
    audit = _clean_environment(_AUDIT)
    gate = _clean_environment(_GATE)

    assert not audit - gate, (
        "the nightly audit hands pytest settings the gate does not, so a test "
        f"can pass one and fail the other: {sorted(audit - gate)}"
    )
    assert gate - audit == _GATE_ONLY, (
        "the gate and the audit have drifted apart on the environment they run "
        "in, and the audit is only evidence about the gate while they agree: "
        f"gate only {sorted(gate - audit)}, expected {sorted(_GATE_ONLY)}"
    )


def test_the_audit_takes_its_ignore_list_from_the_gate_and_never_restates_it() -> None:
    """A second copy of the list is a second suite nobody compared.

    The list moves with the repository. Any spelling of it here that is not a
    read of the gate's own file is a copy that will drift.
    """
    audit = _AUDIT.read_text(encoding="utf-8")
    assert "40-gate.sh" in audit, (
        "the audit no longer reads the gate's file for the ignore list"
    )
    #: The flags themselves may only appear as the pattern being grepped for,
    #: never as literal values this script carries.
    literal_flags = [
        line
        for line in audit.splitlines()
        if "--ignore=" in line
        and "grep" not in line
        and not line.lstrip().startswith("#")
    ]
    assert not literal_flags, (
        f"the audit spells out ignore flags of its own: {literal_flags}"
    )


def test_the_audit_runs_the_export_with_the_exports_own_interpreter() -> None:
    """Tree and interpreter move together or the run reads two trees.

    An editable install in the clone's venv resolves to an absolute path inside
    the clone, and `PYTHONPATH` cannot shadow it. So an interpreter taken from
    the clone imports that package from the clone and everything else from the
    export, which is the reading the export exists to stop.
    """
    audit = _AUDIT.read_text(encoding="utf-8")
    run_lines = [line for line in audit.splitlines() if "/bin/pytest" in line]
    assert run_lines, "the audit does not run a pytest at all"

    from_the_clone = [line for line in run_lines if "$REPO/.venv" in line]
    assert not from_the_clone, (
        "the audit runs the export's tests through the clone's interpreter, so "
        f"its answer is about neither tree: {from_the_clone}"
    )

    assert any("audit_venv" in line for line in run_lines), (
        "the audit's pytest does not come from an environment built for the "
        f"tree under audit: {run_lines}"
    )
    assert "UV_PROJECT_ENVIRONMENT" in audit, (
        "nothing in the audit builds that environment"
    )
