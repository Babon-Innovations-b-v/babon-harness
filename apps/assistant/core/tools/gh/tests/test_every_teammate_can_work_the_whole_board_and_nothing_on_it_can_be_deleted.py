"""Every teammate can work the whole board through the assistant, and nothing on it can be deleted.

WHAT IT PINS. `github_act.execute`, the one board write, with `gh`
replaced by a recorder at its `_gh` seam. A write a teammate asks for runs, as does
one the assistant starts itself; a name the people registry does not hold is refused
before any `gh` call. Editing a title and body, taking an assignee off and
setting the board's Roadmap and Area fields each reach `gh` as the
matching command. The action enum holds no delete, and `ASSISTANT_GITHUB_WRITE`
unset still refuses everything before `gh` is touched.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the rule
that the assistant has full write access to the board, because without it it
cannot help, and the house rules' bound: a teammate is in the registry this
test builds, so they may write; "Mallory" is not, so they may not; the gh CLI
spells the edits `issue edit --title/--body/--remove-assignee`, and a Projects
date field takes `{date:"YYYY-MM-DD"}` in GitHub's GraphQL schema.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.gh import github_act

_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100012,uuid:sam-uuid=Sam:dev:+15550100013"

_LOOKUP = {
    "data": {
        "repository": {
            "issue": {"projectItems": {"nodes": [{"id": "ITEM", "project": {"id": "PROJ", "number": 1}}]}}
        },
        "organization": {
            "projectV2": {
                "field": {
                    "id": "FIELD",
                    "dataType": "SINGLE_SELECT",
                    "options": [{"id": "OPT-DEV", "name": "dev"}, {"id": "OPT-FIN", "name": "finance"}],
                }
            }
        },
    }
}


@pytest.fixture()
def gh_calls(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[list[str]]:
    """Writes armed, a two-person registry, a real audit table, gh recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv("ASSISTANT_GITHUB_WRITE", "1")
    monkeypatch.setenv("GITHUB_ASSISTANT_TOKEN", "test-token")
    state.reset_for_tests()
    calls: list[list[str]] = []

    def _gh(args: list[str], token: str) -> subprocess.CompletedProcess:
        calls.append(args)
        stdout = ""
        if args[:2] == ["api", "graphql"] and args[-1].startswith("query=query"):
            lookup = json.loads(json.dumps(_LOOKUP))
            if "Roadmap" in args[-1]:
                lookup["data"]["organization"]["projectV2"]["field"] = {"id": "DATEFIELD", "dataType": "DATE"}
            stdout = json.dumps(lookup)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(github_act, "_gh", _gh)
    return calls


def test_sams_request_writes_and_assistants_own_does_too(gh_calls) -> None:
    """Any registry name drives a write; so does the assistant itself."""
    answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "on it"}, actor="Sam")
    assert answer.startswith("done:"), answer
    answer = github_act.execute({"action": "reopen", "issue_number": 151}, actor="assistant")
    assert answer.startswith("done:"), answer
    assert [call[:2] for call in gh_calls] == [["issue", "comment"], ["issue", "reopen"]]
    actors = [row["actor"] for row in state.assistant_actions.recent_actions()]
    assert sorted(actors) == ["Sam", "assistant"], actors


def test_a_name_the_registry_does_not_hold_is_refused_before_gh(gh_calls) -> None:
    """Outside the registry, nothing runs."""
    answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "x"}, actor="Mallory")
    assert answer.startswith("refused:"), answer
    assert gh_calls == []


def test_edit_and_unassign_reach_gh_as_issue_edit(gh_calls) -> None:
    """A title/body edit and an unassign are `gh issue edit` calls."""
    answer = github_act.execute(
        {"action": "edit", "issue_number": 12, "title": "New title", "body": "New body"}, actor="Sam"
    )
    assert answer.startswith("done:"), answer
    answer = github_act.execute({"action": "unassign", "issue_number": 12, "assignee": "Robin"}, actor="Sam")
    assert answer.startswith("done:"), answer
    assert gh_calls[0] == ["issue", "edit", "12", "--repo", github_act._REPO,
                           "--title", "New title", "--body", "New body"]
    assert gh_calls[1] == ["issue", "edit", "12", "--repo", github_act._REPO,
                           "--remove-assignee", "robin-example"]


def test_roadmap_and_area_fields_are_set_on_the_card(gh_calls) -> None:
    """A date field takes a date value; Area takes the option by name."""
    answer = github_act.execute(
        {"action": "field", "issue_number": 12, "field": "Roadmap start", "value": "2026-10-01"}, actor="Alex"
    )
    assert answer.startswith("done:"), answer
    answer = github_act.execute(
        {"action": "field", "issue_number": 12, "field": "Area", "value": "area:finance"},
        actor="Alex",
    )
    assert answer.startswith("done:"), answer
    mutations = [call[-1] for call in gh_calls if call[-1].startswith("query=mutation")]
    assert 'fieldId:"DATEFIELD",value:{date:"2026-10-01"}' in mutations[0], mutations[0]
    assert 'value:{singleSelectOptionId:"OPT-FIN"}' in mutations[1], mutations[1]
    refused = github_act.execute(
        {"action": "field", "issue_number": 12, "field": "Roadmap end", "value": "next week"}, actor="Alex"
    )
    assert "YYYY-MM-DD" in refused, refused


def test_nothing_on_the_board_can_be_deleted(gh_calls) -> None:
    """No delete-like action exists, and asking for one runs nothing."""
    actions = github_act.DEFINITION["input_schema"]["properties"]["action"]["enum"]
    assert not [action for action in actions if any(word in action for word in ("delete", "remove", "merge", "transfer"))]
    answer = github_act.execute({"action": "delete", "issue_number": 12}, actor="Alex")
    assert "unknown action" in answer, answer
    assert gh_calls == []


def test_the_kill_switch_still_refuses_everyone(gh_calls, monkeypatch: pytest.MonkeyPatch) -> None:
    """ASSISTANT_GITHUB_WRITE unset: refused before gh, the assistant included."""
    monkeypatch.delenv("ASSISTANT_GITHUB_WRITE")
    for actor in ("Alex", "assistant"):
        answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "x"}, actor=actor)
        assert answer.startswith("refused:") and "ASSISTANT_GITHUB_WRITE" in answer, answer
    assert gh_calls == []
