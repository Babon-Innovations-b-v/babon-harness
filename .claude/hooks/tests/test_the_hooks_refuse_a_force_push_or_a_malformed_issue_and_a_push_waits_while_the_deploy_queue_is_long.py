"""The hooks refuse a force push or a malformed issue, and a push waits while the deploy queue is long.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Pin the issue_guard PreToolUse decisions by driving the real script via stdin.

Runs the script exactly as the harness does: JSON on stdin, exit 2 = block, exit 0 =
allow. Covers the bare-issue block, the complete-issue pass (so the to-prd and triage
skills are never blocked), the MCP path, the optional area check, destructive git, and
fail-open on garbage.

Run: python3 -m pytest .claude/hooks/tests/

A push to main waits while the deploy queue is long, and a commit that unblocks the deploy goes.

WHAT IT PINS. `.claude/hooks/local/push_queue.py`, which `.claude/hooks/local/pre-push`
runs before every push: `undeployed` counts the commits on main before the
newest one marked `vm/deploy` success, and `verdict` refuses when that count
plus the pushed commits passes the limit.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The history is
written by hand: two unmarked commits, then a deployed one, so the queue is 2;
with a limit of 15, ten waiting plus five pushed is 15 and goes, plus six is 16
and is refused, and the trailer lets even 41 through.

WHAT IT WAS PROVED AGAINST. The register row's break makes `verdict` ignore the
limit, so the 16-commit push goes through.

GUARDS. The 2026-11-02 deploy jam: one session pushed 62 commits in an hour.

A push to main is refused only for a red it adds.

WHAT IT PINS. `.claude/hooks/local/push_gate.py`, which the same pre-push runs
after the queue: only a push updating refs/heads/main is read, a register
`--check` that said no (exit 1, no traceback) refuses while one that crashed
does not, a touched test's pytest 1 to 3 refuses while 4, 5, 99 and 124 (no
verdict) let the push go, a red main already had (the same failing file, the
same register line) is not the push's, and the changed paths are the push's
own diff against what main had. Answers are hand-written: a scratch repository
with one commit changing `a.py` is the whole diff. Dropping `"Traceback" not in
output` or reading pytest's 5 as a no fails this. GUARDS. The 2026-11-07
retro: no gate ran on a push, and a module edited without its test reached the
deploy gate unrun.
"""
from __future__ import annotations

import inspect
import pytest


# From issue guard.

import json


import pathlib


import subprocess


import sys


_GUARD = pathlib.Path(__file__).resolve().parent.parent / "issue_guard.py"


_CONFIG = pathlib.Path(__file__).resolve().parents[2] / "project.json"


def _run(payload):
    result = subprocess.run(
        [sys.executable, str(_GUARD)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


def _bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _with_areas(areas):
    """Rewrite project.json's areas for one test, returning the original text."""
    original = _CONFIG.read_text()
    config = json.loads(original)
    config["areas"] = areas
    _CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    return original


_FULL = 'gh issue create --title x --label bug --assignee someone'


def _bare_gh_issue_create_is_blocked():
    code, err = _run(_bash('gh issue create --title "x" --body "y"'))
    assert code == 2
    assert "bare issue creation" in err


def _full_prd_create_passes():
    code, _ = _run(_bash('gh issue create --title "x" --label bug --assignee someone'))
    assert code == 0


def _comma_joined_labels_pass():
    code, _ = _run(_bash('gh issue create --title "x" -l "bug,enhancement" -a someone'))
    assert code == 0


def _equals_form_labels_pass():
    code, _ = _run(_bash('gh issue create --title=x --label=bug --assignee=someone'))
    assert code == 0


def _missing_assignee_is_blocked():
    code, err = _run(_bash("gh issue create --title x --label PRD"))
    assert code == 2
    assert "assignee" in err


def _missing_category_is_blocked():
    code, err = _run(_bash("gh issue create --title x --assignee someone"))
    assert code == 2
    assert "PRD or bug/enhancement" in err


def _bare_mcp_create_issue_is_blocked():
    payload = {"tool_name": "mcp__github__create_issue", "tool_input": {"title": "x"}}
    code, err = _run(payload)
    assert code == 2
    assert "bare issue creation" in err


def _full_mcp_create_issue_passes():
    payload = {
        "tool_name": "mcp__github__create_issue",
        "tool_input": {"title": "x", "labels": ["bug"], "assignees": ["someone"]},
    }
    code, _ = _run(payload)
    assert code == 0


def _area_check_is_off_when_no_areas_configured():
    original = _with_areas([])
    try:
        code, _ = _run(_bash(_FULL))
        assert code == 0
    finally:
        _CONFIG.write_text(original)


def _area_label_required_once_areas_are_configured():
    original = _with_areas(["dev", "art"])
    try:
        code, err = _run(_bash(_FULL))
        assert code == 2
        assert "area:<x>" in err
        code, _ = _run(_bash(_FULL + " --label area:dev"))
        assert code == 0
    finally:
        _CONFIG.write_text(original)


def _non_issue_gh_command_passes():
    code, _ = _run(_bash("gh issue list --label needs-triage"))
    assert code == 0


def _issue_close_with_create_in_comment_passes():
    # A regex matching "create" anywhere after `gh issue` blocks this; the guard is
    # token-based so the word inside the quoted comment is one token, never a match.
    code, _ = _run(_bash(
        'gh issue close 1 --comment "the guard now enforces the create rules"'
    ))
    assert code == 0


def _create_after_close_in_one_line_is_still_blocked():
    # A compound line whose SECOND command is a bare create must still block.
    code, err = _run(_bash('gh issue close 1 --comment "done" && gh issue create --title "x"'))
    assert code == 2
    assert "bare issue creation" in err


def _unrelated_bash_passes():
    code, _ = _run(_bash("ls -la && echo hi"))
    assert code == 0


def _force_push_is_blocked():
    code, err = _run(_bash("git push --force origin main"))
    assert code == 2
    assert "destructive git" in err


def _force_with_lease_is_blocked():
    code, err = _run(_bash("git push --force-with-lease origin main"))
    assert code == 2
    assert "destructive git" in err


def _plus_refspec_push_is_blocked():
    code, err = _run(_bash("git push origin +main:main"))
    assert code == 2
    assert "destructive git" in err


def _reset_hard_is_blocked():
    code, err = _run(_bash("git reset --hard origin/main"))
    assert code == 2
    assert "destructive git" in err


def _normal_push_passes():
    code, _ = _run(_bash("git push origin HEAD:main"))
    assert code == 0


def _force_pattern_inside_a_commit_message_passes():
    code, _ = _run(_bash('git commit -m "note: never run git push -f here"'))
    assert code == 0


def _garbage_stdin_fails_open():
    code, _ = _run("not json at all {{{")
    assert code == 0


def _unbalanced_quotes_fail_open():
    # shlex.split raises on this; the guard must allow rather than crash-block.
    code, _ = _run(_bash('gh issue create --title "unterminated'))
    assert code == 0


def _md_line_number_ref_is_blocked():
    code, err = _run(_bash(_FULL + ' --body "Per plan.md line 117 this holds."'))
    assert code == 2
    assert "numbers in prose rot" in err


def _md_colon_line_ref_is_blocked():
    code, err = _run(_bash(_FULL + ' --body "See notes.md:42 for the claim."'))
    assert code == 2
    assert "numbers in prose rot" in err


def _code_line_ref_stays_allowed():
    code, _ = _run(_bash(_FULL + ' --body "Bug lives in src/dispatcher.py:419"'))
    assert code == 0


def _mcp_body_checks_apply():
    payload = {
        "tool_name": "mcp__github__create_issue",
        "tool_input": {
            "title": "x",
            "labels": ["bug"],
            "assignees": ["someone"],
            "body": "See notes.md:42",
        },
    }
    code, err = _run(payload)
    assert code == 2
    assert "numbers in prose rot" in err


def _each_issue_type_has_its_own_maximum_body_length():
    """A sub-issue is capped below a PRD, a PRD below a vision PRD, a comment on its own; a Budget line lifts it."""
    def create(labels, body):
        return _run({"tool_name": "mcp__github__create_issue", "tool_input": {
            "title": "a size probe", "labels": labels, "assignees": ["someone"], "body": body}})[0]

    root = "## Root check\nNo open root covers this.\n"
    assert create(["bug"], "x" * 3001) == 2
    assert create(["bug"], "x" * 3000) == 0
    assert create(["bug"], "<!-- Budget: a long spec -->\n" + "x" * 5000) == 0
    assert create(["PRD"], root + "x" * 6000) == 2
    assert create(["PRD", "vision"], root + "x" * 6000) == 0
    comment = {"tool_name": "mcp__github__add_issue_comment", "tool_input": {"issue_number": 7, "body": "y" * 2501}}
    assert _run(comment)[0] == 2
    assert _run(_bash("gh issue comment 7 --body " + "y" * 200))[0] == 0


def _a_second_issue_for_open_work_is_refused(tmp_path, monkeypatch):
    """A new sub-issue sharing three subject words with an open one is refused unless `## Duplicate check` names it."""
    open_issues = tmp_path / "open.json"
    open_issues.write_text(json.dumps([
        {"number": 41, "title": "Rename the wire field treatment_path to label", "labels": ["bug"], "parent": None}]))
    monkeypatch.setenv("ISSUE_GUARD_ROOTS", str(open_issues))

    def create(title, body="x"):
        return _run({"tool_name": "mcp__github__create_issue", "tool_input": {
            "title": title, "labels": ["bug"], "assignees": ["someone"], "body": body}})[0]

    assert create("Rename wire field treatment_path everywhere") == 2
    assert create("Rename wire field treatment_path everywhere", "## Duplicate check\n#41 is the API half.") == 0
    assert create("Fix the hero image on mobile") == 0

# From a push waits while the deploy queue is long and an unblocking commit goes.

import importlib.util


_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "local" / "push_queue.py"


def _push_queue():
    spec = importlib.util.spec_from_file_location("push_queue", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _commit(deployed: bool) -> dict:
    contexts = [{"context": "vm/deploy", "state": "SUCCESS"}] if deployed else []
    return {"oid": "x", "status": {"contexts": contexts}}


def _a_push_waits_while_the_deploy_queue_is_long_and_an_unblocking_commit_goes() -> None:
    """The queue is counted to the newest deployed commit; past the limit refuses, the trailer passes."""
    queue = _push_queue()
    assert queue.undeployed([_commit(False), _commit(False), _commit(True), _commit(False)]) == 2
    assert queue.undeployed([_commit(False)]) is None
    assert queue.verdict(10, 5, False, limit=15) is None
    assert "BLOCKED" in queue.verdict(10, 6, False, limit=15)
    assert queue.verdict(40, 1, True, limit=15) is None


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


_GATE_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "local" / "push_gate.py"


def _a_push_is_refused_only_for_a_red_it_adds_to_main(tmp_path):
    spec = importlib.util.spec_from_file_location("push_gate", _GATE_SCRIPT)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    zero, tip, had = "0" * 40, "b" * 40, "a" * 40
    assert gate.pushed_tips([
        f"HEAD {tip} refs/heads/main {had}\n",
        f"HEAD {tip} refs/heads/other {had}\n",
        f"(delete) {zero} refs/heads/main {had}\n",
        "garbage\n",
    ]) == [(tip, had)]
    assert gate.refusal("register", 1, "x has no row in the register") is not None
    assert gate.refusal("register", 1, "Traceback (most recent call last):") is None
    assert gate.refusal("register", 0, "") is None
    assert all(gate.refusal("touched tests", verdict, "1 failed") for verdict in (1, 2, 3))
    assert not any(gate.refusal("touched tests", verdict, "") for verdict in (0, 4, 5, 99, 124))
    pushed = "FAILED a/tests/test_a.py::test_a[x] - boom\nERROR b/tests/test_b.py - nope\n2 failed\n"
    assert gate.failed_files(pushed) == {"a/tests/test_a.py", "b/tests/test_b.py"}
    assert gate.new_reds("touched tests", pushed, "FAILED a/tests/test_a.py::test_a[y]\n") == {"b/tests/test_b.py"}
    assert gate.new_reds("touched tests", pushed, pushed) == set()
    assert gate.new_reds("register", "register: x\nregister: y\n", "register: x\n") == {"register: y"}
    assert gate.new_reds("register", "register: x\n", "register: x\nregister: y\n") == set()
    repo = tmp_path / "push"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null"]
    subprocess.run([*git, "init", "-q"], check=True, env=gate._env())
    for name in ("first.py", "a.py"):
        (repo / name).write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*git, "add", name], check=True, env=gate._env())
        subprocess.run([*git, "commit", "-qm", name], check=True, env=gate._env())
    head, parent = (subprocess.run([*git, "rev-parse", ref], capture_output=True, text=True, check=True,
                                   env=gate._env()).stdout.strip() for ref in ("HEAD", "HEAD^"))
    assert gate.changed_paths(repo, head, parent) == ["a.py"]
    assert gate.changed_paths(repo, head, zero) == []


CASES = [
    *_cases(_bare_gh_issue_create_is_blocked),
    *_cases(_full_prd_create_passes),
    *_cases(_comma_joined_labels_pass),
    *_cases(_equals_form_labels_pass),
    *_cases(_missing_assignee_is_blocked),
    *_cases(_missing_category_is_blocked),
    *_cases(_bare_mcp_create_issue_is_blocked),
    *_cases(_full_mcp_create_issue_passes),
    *_cases(_area_check_is_off_when_no_areas_configured),
    *_cases(_area_label_required_once_areas_are_configured),
    *_cases(_non_issue_gh_command_passes),
    *_cases(_issue_close_with_create_in_comment_passes),
    *_cases(_create_after_close_in_one_line_is_still_blocked),
    *_cases(_unrelated_bash_passes),
    *_cases(_force_push_is_blocked),
    *_cases(_force_with_lease_is_blocked),
    *_cases(_plus_refspec_push_is_blocked),
    *_cases(_reset_hard_is_blocked),
    *_cases(_normal_push_passes),
    *_cases(_force_pattern_inside_a_commit_message_passes),
    *_cases(_garbage_stdin_fails_open),
    *_cases(_unbalanced_quotes_fail_open),
    *_cases(_md_line_number_ref_is_blocked),
    *_cases(_md_colon_line_ref_is_blocked),
    *_cases(_code_line_ref_stays_allowed),
    *_cases(_mcp_body_checks_apply),
    *_cases(_each_issue_type_has_its_own_maximum_body_length),
    *_cases(_a_second_issue_for_open_work_is_refused),
    *_cases(_a_push_waits_while_the_deploy_queue_is_long_and_an_unblocking_commit_goes),
    *_cases(_a_push_is_refused_only_for_a_red_it_adds_to_main),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_hooks_refuse_a_force_push_or_a_malformed_issue_and_a_push_waits_while_the_deploy_queue_is_long(scenario, given, uses, request):
    """The hooks refuse a force push or a malformed issue, and a push waits while the deploy queue is long: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
