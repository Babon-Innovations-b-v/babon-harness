"""A deploy cycle runs its steps once in order, rebuilds only what changed, and every gate verdict reaches the arm and the alert meant for it.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A change rebuilds the services of the fragment it belongs to, and no others.

WHAT IT PINS. `infra/auto-deploy/compose_fragments.py`, which step 50 and the
verifying lane both ask which compose services one commit changes.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A small tree is
written by hand: two fragments, each declaring its services, one of them also
watching `design/` through `x-deploy-paths`. Which services a path must select
follows from the layout rule in the module's docstring, read off the tree
written here, never from an earlier answer.

WHAT IT WAS PROVED AGAINST. Matching a changed path against the fragment's
directory without the trailing separator, so `apps/web` also claims
`apps/website`.

GUARDS. Step 50 restarts only what a commit changed.

A deploy alert is a log line unless its sender says a person must act.

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

One rejected commit is one alert, and never none.

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

With the eject off, a red is answered by nothing: no claim, no clone, no push.

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

Each pytest exit code must reach its own arm of step 40's verdict chain.

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

Every numbered step is sourced exactly once, in order, after the lock.

WHAT IT PINS. The explicit source list in `auto-deploy.sh` against the step
files in `steps/`. A step missing from the list never runs and nothing says so;
a step sourced before the lock races a cycle already in flight.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The directory
listing is the oracle: every `NN-*.sh` file must appear once, in lexical order,
and `00-lock.sh` first. Files that are not steps (doors.sh, eject_body.sh,
build_verdict.sh) must never be in the list.

WHAT IT WAS PROVED AGAINST. Dropping a step from the source list.

GUARDS. The orchestrator owns ordering only.

Settings load committed file first, vault cache second, caller's environment wins.

WHAT IT PINS. `harness_load_config` in `steps/doors.sh`, which every deploy
script uses to read config/harness.env and the vault cache.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Two files are
written by hand, each setting keys the other also sets, and one key is set in
the caller's environment too. Which value must win follows from the documented
order, written here, never from an earlier run. The loader must also never
EXECUTE a file: a value that would run a command if sourced stays text.

WHAT IT WAS PROVED AGAINST. Letting a file override a key already in the
environment, which is how a hand run's override would silently not apply.

GUARDS. The three-place configuration contract.

Step 80 removes a unit only when IT installed it and the repository dropped it.

WHAT IT PINS. `_install_units` in `steps/80-units.sh`: units found in
`*/<name>/systemd/` are installed, and the manifest of what was installed is
the only list removal reads, so a unit the owner installed by hand survives.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A verified tree
with one unit, a unit directory holding a hand-installed unit and a unit the
manifest says this step installed earlier, and stubs for sudo and systemctl.
What must remain follows from the rule above.

WHAT IT WAS PROVED AGAINST. Sweeping every installed `harness-*` unit the tree
lacks, which deletes the hand-installed one.

GUARDS. Step 80's orphan sweep.
"""
from __future__ import annotations

import inspect


# From a change rebuilds the services of its own fragment and no others.

import importlib.util


from pathlib import Path


_MODULE = Path(__file__).resolve().parents[1] / "compose_fragments.py"


def _load():
    spec = importlib.util.spec_from_file_location("compose_fragments", _MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "apps/website").mkdir(parents=True)
    (tmp_path / "apps/website/compose.yml").write_text(
        "# the site\n"
        "x-deploy-paths:\n"
        "  - design/\n"
        "services:\n"
        "  website:\n"
        "    build:\n"
        "      context: ../..\n"
        "    healthcheck:\n"
        "      test: [\"CMD\", \"true\"]\n",
        encoding="utf-8",
    )
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / "apps/web/compose.yml").write_text(
        "services:\n  web:\n    image: nginx\n  web-worker:\n    image: nginx\n"
        "volumes:\n  data:\n",
        encoding="utf-8",
    )
    return tmp_path


def _a_change_inside_a_fragment_selects_its_services_only(tmp_path: Path) -> None:
    module = _load()
    repo = _tree(tmp_path)
    assert module.changed_services(repo, ["apps/website/Dockerfile"]) == ["website"]
    assert module.changed_services(repo, ["apps/web/nginx.conf"]) == ["web", "web-worker"]


def _a_watched_path_outside_the_fragment_selects_it(tmp_path: Path) -> None:
    module = _load()
    assert module.changed_services(_tree(tmp_path), ["design/tokens.css"]) == ["website"]


def _the_root_compose_file_or_config_selects_everything(tmp_path: Path) -> None:
    module = _load()
    repo = _tree(tmp_path)
    assert module.changed_services(repo, ["docker-compose.yml"]) == ["all"]
    assert module.changed_services(repo, ["config/harness.env.example"]) == ["all"]


def _a_path_no_fragment_owns_selects_nothing(tmp_path: Path) -> None:
    module = _load()
    assert module.changed_services(_tree(tmp_path), ["docs/bible.md", "tools/x.py"]) == []

# From a deploy alert wakes nobody unless the sender says a person must act.

import subprocess


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


def _an_unmarked_alert_is_a_record_and_sends_nothing(tmp_path: Path) -> None:
    argv, log = _sent(tmp_path, "auto-deploy: something happened", "the body")
    assert argv == [], f"an unmarked alert was sent: {argv}"
    assert "RECORD: auto-deploy: something happened" in log


def _a_marked_alert_is_sent_with_its_markings(tmp_path: Path) -> None:
    argv, log = _sent(
        tmp_path, "auto-deploy: no room", "the body", "--blocks-deploy", "yes", "--wakes-somebody"
    )
    assert argv[1:4] == ["auto-deploy: no room", "the body", "blocks-deploy=yes"], argv
    assert "ALERT: auto-deploy: no room" in log


def _the_page_carries_the_markings_as_facts() -> None:
    spec = importlib.util.spec_from_file_location("notify", _NOTIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.payload("s", "b", []) == {"subject": "s", "body": "b", "source": "auto-deploy"}
    assert module.payload("s", "b", ["blocks-deploy=yes"])["facts"] == {"blocks_deploy": "yes"}

# From a rejected commit is one alert and with the eject armed it is the ejects.

import pytest


_STEP = Path(__file__).resolve().parents[1] / "steps" / "40-gate.sh"


#: The line the rc chain opens on, and the arms that close it. Same anchors as
#: the gate-exit-code cases, because it is the same chain read for a different
#: question.
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


def _an_armed_eject_means_the_gate_does_not_page(tmp_path: Path) -> None:
    """The eject's hand-back follows in this same cycle and says more."""
    pages = _pages_for(tmp_path, "1")
    assert pages == [], (
        "step 40 paged for a commit the eject is about to take off main and "
        f"hand back itself: {pages}"
    )


def _a_disarmed_eject_means_the_gate_is_the_only_voice(tmp_path: Path) -> None:
    """Nothing else will speak, so this arm must.

    With the eject off the commit stays on `main` and no revert follows.
    Quietening this arm as well would turn a rejected commit into silence.
    """
    pages = _pages_for(tmp_path, "0")
    assert len(pages) == 1, (
        f"expected exactly one page with the eject off, got {pages}"
    )
    assert "gate-red" in pages[0], f"the page is not the gate's red: {pages[0]}"


def _the_arm_still_does_everything_else_it_did(tmp_path: Path, armed: str) -> None:
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

# From an eject that is off decides nothing and claims nothing.

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


def _off_decides_nothing(tmp_path: Path) -> None:
    recorded = _decide(tmp_path, "0")
    assert "OUTCOME off eject_off" in recorded, recorded
    assert "arm " not in recorded and "gh_" not in recorded, recorded
    assert not (tmp_path / "ejected").exists(), "the off switch still claimed the commit"


def _armed_reaches_the_preconditions(tmp_path: Path) -> None:
    recorded = _decide(tmp_path, "1")
    assert "OUTCOME declined" in recorded, recorded

# From every gate exit code reaches the arm that is for it.

#: The line the chain opens on.
_CHAIN_OPENS_5 = '    if [ "$gate_rc" -eq 0 ]; then'


#: Every helper the chain calls. Each becomes a stub that appends one line to
#: $CALLS, so what an arm did is a list of names rather than a side effect.
_STUBBED_5 = (
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


def _chain_5() -> str:
    """The whole chain: the opening line to the `fi` that closes its last arm.

    Found by the chain's own arms rather than by counting keywords. A regex for
    the first `fi` at this indentation stops inside the first arm, which
    silently tests a quarter of the thing and passes; counting `if`/`fi` trips
    over the `case`, the `[ ... ] &&` and the command substitutions inside the
    arms. The arms themselves are unambiguous: they are the only lines in the
    file that start with four spaces and `elif [ "$gate_rc"`.
    """
    lines = _STEP.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line == _CHAIN_OPENS_5]
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
        f'{name}() {{ echo "{name} $*" >> "$CALLS"; return 0; }}' for name in _STUBBED_5
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
        _chain_5(),
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


def _a_suite_that_passed_records_a_green_verdict(tmp_path: Path) -> None:
    """rc=0 is the only arm that may cache a green verdict or say success."""
    lines = _run(tmp_path, 0)
    assert any(line.startswith("record_gate_verdict green") for line in lines), lines
    assert any("vm/gate success" in line for line in lines), lines
    assert "gate_red=0" in _final(lines), lines


def _a_suite_that_failed_is_a_regression_and_ships_nothing(tmp_path: Path) -> None:
    """rc=1 with no lost worker is the one verdict the eject acts on."""
    lines = _run(tmp_path, 1)
    final = _final(lines)
    assert "gate_red=1" in final, lines
    assert "reason=regression" in final, lines
    assert not any("record_gate_verdict green" in line for line in lines), lines


def _a_tree_that_could_not_be_collected_is_red(
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


def _a_run_that_never_finished_holds_without_ejecting(
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


def _a_green_run_never_lands_on_the_amber_arm(tmp_path: Path) -> None:
    """The regression itself, stated as its own case.

    Splitting the rc=0 arm into a second top-level `if` detaches the `elif`
    arms, and rc=0 then falls through to the `else`. A detached chain would
    report "gate could not run (rc=0)", which contradicts itself: rc=0 IS the
    run finishing.
    """
    lines = _run(tmp_path, 0)
    assert not any("could not run" in line for line in lines), lines
    assert not any("vm/gate error" in line for line in lines), lines

# From every step is sourced once in order and the lock is first.

import re


_HERE = Path(__file__).resolve().parents[1]


def _the_source_list_is_the_step_directory_in_order() -> None:
    text = (_HERE / "auto-deploy.sh").read_text(encoding="utf-8")
    sourced = re.findall(r'^\. "\$AUTO_DEPLOY_DIR/steps/([^"]+)"', text, flags=re.MULTILINE)
    steps = sorted(path.name for path in (_HERE / "steps").glob("[0-9][0-9]-*.sh"))
    assert sourced == steps, f"source list {sourced} does not match the steps {steps}"
    assert sourced[0] == "00-lock.sh"
    for helper in ("doors.sh", "eject_body.sh", "build_verdict.sh"):
        assert helper not in sourced, f"{helper} is not a step and must not be sourced as one"

# From the settings load in order and never override the callers own.

def _the_vault_wins_over_the_settings_and_the_caller_wins_over_both(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/harness.env").write_text(
        "# settings\nDOMAIN=example.org\nEJECT_ENABLED=0\nSHARED=from-settings\n"
        "export QUOTED='a b'\nTRAP=$(touch " + str(tmp_path / "ran") + ")\n",
        encoding="utf-8",
    )
    vault = tmp_path / "harness.env"
    vault.write_text('SHARED="from-vault"\nEJECT_ENABLED=1\n', encoding="utf-8")
    script = "\n".join((
        f'. "{_DOORS}"',
        f'HARNESS_ENV_FILE="{vault}" harness_load_config "{repo}"',
        'printf "%s|%s|%s|%s|%s\\n" "$DOMAIN" "$SHARED" "$EJECT_ENABLED" "$QUOTED" "$TRAP"',
    ))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "EJECT_ENABLED": "caller"},
    )
    assert done.stdout.strip() == "example.org|from-vault|caller|a b|$(touch " + str(tmp_path / "ran") + ")"
    assert not (tmp_path / "ran").exists(), "the loader executed a value"

# From the unit sweep removes only what it installed.

_STEPS = Path(__file__).resolve().parents[1] / "steps"


def _only_a_dropped_unit_this_step_installed_is_removed(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "infra/thing/systemd").mkdir(parents=True)
    (tree / "infra/thing/systemd/harness-thing.timer").write_text(
        "[Timer]\nOnCalendar=daily\nUnit=harness-thing.service\n", encoding="utf-8"
    )
    units = tmp_path / "units"
    units.mkdir()
    (units / "harness-by-hand.service").write_text("[Service]\n", encoding="utf-8")
    (units / "harness-dropped.service").write_text("[Service]\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "installed-units").write_text("harness-dropped.service\nharness-thing.timer\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "systemctl").chmod(0o755)
    script = "\n".join((
        "set -u",
        f'export PATH="{bin_dir}:/usr/bin:/bin"',
        f'LOG="{tmp_path}/log"',
        'log() { echo "$*" >> "$LOG"; }',
        f'. "{_STEPS}/doors.sh"',
        f'STATE_DIR="{state}"',
        f'UNIT_DIR="{units}"',
        'UNIT_SUDO=""',
        f'VERIFIED_TREE="{tree}"',
        "gate_red=0",
        f'. "{_STEPS}/80-units.sh"',
    ))
    subprocess.run(["bash", "-c", script], check=True, timeout=30, capture_output=True)
    remaining = sorted(path.name for path in units.iterdir())
    assert remaining == ["harness-by-hand.service", "harness-thing.timer"], remaining
    assert (state / "installed-units").read_text(encoding="utf-8").split() == ["harness-thing.timer"]


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_change_inside_a_fragment_selects_its_services_only),
    *_cases(_a_watched_path_outside_the_fragment_selects_it),
    *_cases(_the_root_compose_file_or_config_selects_everything),
    *_cases(_a_path_no_fragment_owns_selects_nothing),
    *_cases(_an_unmarked_alert_is_a_record_and_sends_nothing),
    *_cases(_a_marked_alert_is_sent_with_its_markings),
    *_cases(_the_page_carries_the_markings_as_facts),
    *_cases(_an_armed_eject_means_the_gate_does_not_page),
    *_cases(_a_disarmed_eject_means_the_gate_is_the_only_voice),
    *_cases(_the_arm_still_does_everything_else_it_did, "armed", ["1", "0"]),
    *_cases(_off_decides_nothing),
    *_cases(_armed_reaches_the_preconditions),
    *_cases(_a_suite_that_passed_records_a_green_verdict),
    *_cases(_a_suite_that_failed_is_a_regression_and_ships_nothing),
    *_cases(_a_tree_that_could_not_be_collected_is_red, 
    ("gate_rc", "reason"),
    [(2, "broken_tree"), (3, "broken_tree"), (4, "broken_tree"), (5, "no_tests_collected")],
),
    *_cases(_a_run_that_never_finished_holds_without_ejecting, "gate_rc", [124, 126, 127, 137]),
    *_cases(_a_green_run_never_lands_on_the_amber_arm),
    *_cases(_the_source_list_is_the_step_directory_in_order),
    *_cases(_the_vault_wins_over_the_settings_and_the_caller_wins_over_both),
    *_cases(_only_a_dropped_unit_this_step_installed_is_removed),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_deploy_cycle_runs_its_steps_once_in_order_and_every_gate_verdict_reaches_the_arm_and_the_alert_meant_for_it(scenario, given, uses, request):
    """A deploy cycle runs its steps once in order, rebuilds only what changed, and every gate verdict reaches the arm and the alert meant for it: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
