"""Pin the issue_guard PreToolUse decisions by driving the real script via stdin.

Runs the script exactly as the harness does: JSON on stdin, exit 2 = block, exit 0 =
allow. Covers the bare-issue block, the complete-issue pass (so the to-prd and triage
skills are never blocked), the MCP path, the optional area check, destructive git, and
fail-open on garbage.

Run: python3 -m pytest .claude/hooks/tests/
"""

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


def test_bare_gh_issue_create_is_blocked():
    code, err = _run(_bash('gh issue create --title "x" --body "y"'))
    assert code == 2
    assert "bare issue creation" in err


def test_full_prd_create_passes():
    code, _ = _run(_bash('gh issue create --title "x" --label bug --assignee someone'))
    assert code == 0


def test_comma_joined_labels_pass():
    code, _ = _run(_bash('gh issue create --title "x" -l "bug,enhancement" -a someone'))
    assert code == 0


def test_equals_form_labels_pass():
    code, _ = _run(_bash('gh issue create --title=x --label=bug --assignee=someone'))
    assert code == 0


def test_missing_assignee_is_blocked():
    code, err = _run(_bash("gh issue create --title x --label PRD"))
    assert code == 2
    assert "assignee" in err


def test_missing_category_is_blocked():
    code, err = _run(_bash("gh issue create --title x --assignee someone"))
    assert code == 2
    assert "PRD or bug/enhancement" in err


def test_bare_mcp_create_issue_is_blocked():
    payload = {"tool_name": "mcp__github__create_issue", "tool_input": {"title": "x"}}
    code, err = _run(payload)
    assert code == 2
    assert "bare issue creation" in err


def test_full_mcp_create_issue_passes():
    payload = {
        "tool_name": "mcp__github__create_issue",
        "tool_input": {"title": "x", "labels": ["bug"], "assignees": ["someone"]},
    }
    code, _ = _run(payload)
    assert code == 0


def test_area_check_is_off_when_no_areas_configured():
    original = _with_areas([])
    try:
        code, _ = _run(_bash(_FULL))
        assert code == 0
    finally:
        _CONFIG.write_text(original)


def test_area_label_required_once_areas_are_configured():
    original = _with_areas(["dev", "art"])
    try:
        code, err = _run(_bash(_FULL))
        assert code == 2
        assert "area:<x>" in err
        code, _ = _run(_bash(_FULL + " --label area:dev"))
        assert code == 0
    finally:
        _CONFIG.write_text(original)


def test_non_issue_gh_command_passes():
    code, _ = _run(_bash("gh issue list --label needs-triage"))
    assert code == 0


def test_issue_close_with_create_in_comment_passes():
    # A regex matching "create" anywhere after `gh issue` blocks this; the guard is
    # token-based so the word inside the quoted comment is one token, never a match.
    code, _ = _run(_bash(
        'gh issue close 1 --comment "the guard now enforces the create rules"'
    ))
    assert code == 0


def test_create_after_close_in_one_line_is_still_blocked():
    # A compound line whose SECOND command is a bare create must still block.
    code, err = _run(_bash('gh issue close 1 --comment "done" && gh issue create --title "x"'))
    assert code == 2
    assert "bare issue creation" in err


def test_unrelated_bash_passes():
    code, _ = _run(_bash("ls -la && echo hi"))
    assert code == 0


def test_force_push_is_blocked():
    code, err = _run(_bash("git push --force origin main"))
    assert code == 2
    assert "destructive git" in err


def test_force_with_lease_is_blocked():
    code, err = _run(_bash("git push --force-with-lease origin main"))
    assert code == 2
    assert "destructive git" in err


def test_plus_refspec_push_is_blocked():
    code, err = _run(_bash("git push origin +main:main"))
    assert code == 2
    assert "destructive git" in err


def test_reset_hard_is_blocked():
    code, err = _run(_bash("git reset --hard origin/main"))
    assert code == 2
    assert "destructive git" in err


def test_normal_push_passes():
    code, _ = _run(_bash("git push origin HEAD:main"))
    assert code == 0


def test_force_pattern_inside_a_commit_message_passes():
    code, _ = _run(_bash('git commit -m "note: never run git push -f here"'))
    assert code == 0


def test_garbage_stdin_fails_open():
    code, _ = _run("not json at all {{{")
    assert code == 0


def test_unbalanced_quotes_fail_open():
    # shlex.split raises on this; the guard must allow rather than crash-block.
    code, _ = _run(_bash('gh issue create --title "unterminated'))
    assert code == 0


def test_md_line_number_ref_is_blocked():
    code, err = _run(_bash(_FULL + ' --body "Per plan.md line 117 this holds."'))
    assert code == 2
    assert "numbers in prose rot" in err


def test_md_colon_line_ref_is_blocked():
    code, err = _run(_bash(_FULL + ' --body "See notes.md:42 for the claim."'))
    assert code == 2
    assert "numbers in prose rot" in err


def test_code_line_ref_stays_allowed():
    code, _ = _run(_bash(_FULL + ' --body "Bug lives in src/dispatcher.py:419"'))
    assert code == 0


def test_mcp_body_checks_apply():
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


def test_each_issue_type_has_its_own_maximum_body_length():
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


def test_a_second_issue_for_open_work_is_refused(tmp_path, monkeypatch):
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

