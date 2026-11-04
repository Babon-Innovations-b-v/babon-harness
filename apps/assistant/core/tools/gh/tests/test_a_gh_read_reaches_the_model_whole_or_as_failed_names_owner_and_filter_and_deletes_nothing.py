"""A gh read reaches the model as failed when gh fails, keeps the newest comment under the budget, names each issue's owner and the filter that ran, and nothing on the board can be deleted.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A gh read whose `gh` call exits non-zero answers with a typed failure.

WHAT IT PINS. `execute` of `gh_issue_view`, `gh_pr_view` and `gh_commits`, the
tool modules' public interface: when the `gh` subprocess exits non-zero, the
answer is a `ToolResult` with status FAILED carrying gh's stderr, and the
registry renders it to the model opening "FAILED [", never "OK [".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. `gh` exits 1
with "Could not resolve to an Issue" on a lookup it could not make; that is
gh's own statement that no answer was obtained, so the only honest status is
FAILED. The stub reproduces that exit code and stderr verbatim.

An issue or PR view too long for the budget keeps its newest comment.

WHAT IT PINS. `execute` of `gh_issue_view` and `gh_pr_view`, the tool modules'
public interface: when the overview plus the comments run past the per-result
byte budget, the oldest comments are cut, the newest comment survives, the
overview's title survives, the cut is marked, and the answer stays inside the
budget.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. `gh ... view
--comments` prints comments oldest first, so the newest comment is the last
block of its stdout. The stub writes 40 comments of about 300 bytes each, far
past 8 KiB, and the last one carries a unique marker; that marker must appear,
the first comment's marker must not.

Every issue the assistant lists names its owner, and the listing names its filter.

WHAT IT PINS. `gh_issue_list.execute` with `subprocess.run` replaced, and
`changes.digest_since` with `changes._run_gh` replaced: each issue row carries
`owner: <login>`, an issue with nobody on it says `owner: unassigned` in
words, the gh listing opens with the filter that ran, and a gh failure is a
FAILED result rather than text the seam would label OK.

WHY IT EXISTS. Plain `gh issue list` prints no assignee column and the change
feed asked gh for none, so a missing column read as "nobody owns this": an
issue out of an `assignee:alex-example` search could be called unowned, and a
teammate's issue could land in the owner's list.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The gh JSON
payload is written by hand in the shape `gh issue list --json` documents
(`assignees` is a list of objects with a `login`), so the expected owner of
each row is read straight off the fixture.

Every teammate can work the whole board through the assistant, and nothing on it can be deleted.

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

import inspect


# From a gh read whose gh call exits non zero reaches the model as failed.

import subprocess


import pytest


from apps.assistant.core import tools


from apps.assistant.core.tools.gh import gh_commits, gh_issue_view, gh_pr_view


from apps.assistant.core.tools.meta import result


_STDERR = "GraphQL: Could not resolve to an Issue with the number of 38."


def _gh_refuses(*args, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=_STDERR)


def _a_gh_read_whose_gh_call_exits_non_zero_reaches_the_model_as_failed(
    monkeypatch, module, tool_input
) -> None:
    """The module answers FAILED with gh's stderr, and the model reads FAILED."""
    monkeypatch.setattr(module.subprocess, "run", _gh_refuses)
    answer = module.execute(tool_input)
    assert isinstance(answer, result.ToolResult)
    assert answer.status == result.FAILED
    assert _STDERR in answer.error
    assert tools.execute(module.NAME, tool_input).startswith(f"FAILED [{module.NAME} @ ")

# From an issue or pr view too long for the budget keeps its newest comment.

_TITLE = "title:\tOffice lease renewal"


_OLDEST = "COMMENT-0000-OLDEST"


_NEWEST = "COMMENT-0039-NEWEST request sent to the landlord on 28 Sep"


def _comments() -> str:
    blocks = [f"author:\talex-example\n{_OLDEST}\n" + "x" * 280]
    blocks += [f"author:\talex-example\ncomment {index}\n" + "y" * 280 for index in range(1, 39)]
    blocks.append(f"author:\talex-example\n{_NEWEST}\n")
    return "\n--\n".join(blocks)


def _gh(args, **kwargs) -> subprocess.CompletedProcess[str]:
    stdout = _comments() if "--comments" in args else f"{_TITLE}\nstate:\tOPEN\n\nbody text"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def _an_issue_or_pr_view_too_long_for_the_budget_keeps_its_newest_comment(
    monkeypatch, module, tool_input
) -> None:
    """The newest comment and the title survive, the oldest is cut, the cut is marked."""
    monkeypatch.setattr(module.subprocess, "run", _gh)
    answer = module.execute(tool_input)
    assert _NEWEST in answer
    assert _TITLE in answer
    assert _OLDEST not in answer
    assert "cut" in answer
    assert len(answer.encode("utf-8")) <= 8192

# From every listed issue names its owner and the filter that ran.

import json


from typing import Any


from apps.assistant.core import changes


from apps.assistant.core.tools.gh import gh_issue_list


_ISSUES = [
    {"number": 82, "title": "Deploy phase metrics", "state": "OPEN",
     "updatedAt": "2026-09-07T09:00:00Z", "labels": [{"name": "enhancement"}],
     "assignees": [{"login": "alex-example"}]},
    {"number": 1, "title": "Write the onboarding guide", "state": "OPEN",
     "updatedAt": "2026-09-09T09:00:00Z", "labels": [],
     "assignees": [{"login": "sam-example"}]},
    {"number": 2, "title": "Nobody on this", "state": "OPEN",
     "updatedAt": "2026-09-10T09:00:00Z", "labels": [], "assignees": []},
    {"number": 91, "title": "Done already", "state": "CLOSED",
     "updatedAt": "2026-09-11T09:00:00Z", "labels": [], "assignees": [{"login": "sam-example"}]},
]


def _fake_gh_payload(argv: list[str]) -> str:
    """What gh would print for `--json <fields>`: only the asked-for fields."""
    fields = argv[argv.index("--json") + 1].split(",") if "--json" in argv else []
    return json.dumps([{field: issue[field] for field in fields if field in issue} for issue in _ISSUES])


def _row_for(text: str, number: int) -> str:
    return next(line for line in text.splitlines() if f"#{number} " in line)


def _the_issue_list_names_every_owner_and_its_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each row says whose it is; the first line says which search ran."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, _fake_gh_payload(argv), "")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({"search": "assignee:alex-example state:open"})
    assert outcome.status == result.OK
    assert outcome.data.splitlines()[0] == "filter: search 'assignee:alex-example state:open' (state open)"
    assert "owner: alex-example" in _row_for(outcome.data, 82)
    assert "owner: sam-example" in _row_for(outcome.data, 1)
    assert "owner: unassigned" in _row_for(outcome.data, 2)


def _every_listed_issue_says_whether_it_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """With state all, each row still says OPEN or CLOSED: the filter line
    cannot, and plain `gh issue list` printed the state on every row."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, _fake_gh_payload(argv), "")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({"state": "all"})
    assert "#82 [OPEN] " in _row_for(outcome.data, 82)
    assert "#91 [CLOSED] " in _row_for(outcome.data, 91)


def _a_failed_listing_is_failed_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """gh exiting non-zero comes back FAILED with its stderr."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "HTTP 502")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({})
    assert outcome.status == result.FAILED
    assert "HTTP 502" in outcome.error


def _the_change_feed_names_every_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """The digest a report grounds on carries the owner on each issue line."""
    def _gh(args: list[str]) -> tuple[int, str, str]:
        if args[0] == "api":
            return 0, "", ""
        return 0, _fake_gh_payload(args), ""

    monkeypatch.setattr(changes, "_run_gh", _gh)
    digest = changes.digest_since("2026-09-07T06:00:00Z")
    assert "owner: alex-example" in _row_for(digest, 82)
    assert "owner: sam-example" in _row_for(digest, 1)
    assert "owner: unassigned" in _row_for(digest, 2)

# From every teammate can work the whole board and nothing on it can be deleted.

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


def _sams_request_writes_and_assistants_own_does_too(gh_calls) -> None:
    """Any registry name drives a write; so does the assistant itself."""
    answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "on it"}, actor="Sam")
    assert answer.startswith("done:"), answer
    answer = github_act.execute({"action": "reopen", "issue_number": 151}, actor="assistant")
    assert answer.startswith("done:"), answer
    assert [call[:2] for call in gh_calls] == [["issue", "comment"], ["issue", "reopen"]]
    actors = [row["actor"] for row in state.assistant_actions.recent_actions()]
    assert sorted(actors) == ["Sam", "assistant"], actors


def _a_name_the_registry_does_not_hold_is_refused_before_gh(gh_calls) -> None:
    """Outside the registry, nothing runs."""
    answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "x"}, actor="Mallory")
    assert answer.startswith("refused:"), answer
    assert gh_calls == []


def _edit_and_unassign_reach_gh_as_issue_edit(gh_calls) -> None:
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


def _roadmap_and_area_fields_are_set_on_the_card(gh_calls) -> None:
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


def _nothing_on_the_board_can_be_deleted(gh_calls) -> None:
    """No delete-like action exists, and asking for one runs nothing."""
    actions = github_act.DEFINITION["input_schema"]["properties"]["action"]["enum"]
    assert not [action for action in actions if any(word in action for word in ("delete", "remove", "merge", "transfer"))]
    answer = github_act.execute({"action": "delete", "issue_number": 12}, actor="Alex")
    assert "unknown action" in answer, answer
    assert gh_calls == []


def _the_kill_switch_still_refuses_everyone(gh_calls, monkeypatch: pytest.MonkeyPatch) -> None:
    """ASSISTANT_GITHUB_WRITE unset: refused before gh, the assistant included."""
    monkeypatch.delenv("ASSISTANT_GITHUB_WRITE")
    for actor in ("Alex", "assistant"):
        answer = github_act.execute({"action": "comment", "issue_number": 151, "body": "x"}, actor=actor)
        assert answer.startswith("refused:") and "ASSISTANT_GITHUB_WRITE" in answer, answer
    assert gh_calls == []


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
    *_cases(_a_gh_read_whose_gh_call_exits_non_zero_reaches_the_model_as_failed, 
    ("module", "tool_input"),
    [
        (gh_issue_view, {"issue_number": 38}),
        (gh_pr_view, {"pr_number": 38}),
        (gh_commits, {"branch": "main"}),
    ],
),
    *_cases(_an_issue_or_pr_view_too_long_for_the_budget_keeps_its_newest_comment, 
    ("module", "tool_input"),
    [
        (gh_issue_view, {"issue_number": 38}),
        (gh_pr_view, {"pr_number": 38}),
    ],
),
    *_cases(_the_issue_list_names_every_owner_and_its_filter),
    *_cases(_every_listed_issue_says_whether_it_is_open),
    *_cases(_a_failed_listing_is_failed_not_ok),
    *_cases(_the_change_feed_names_every_owner),
    *_cases(_sams_request_writes_and_assistants_own_does_too),
    *_cases(_a_name_the_registry_does_not_hold_is_refused_before_gh),
    *_cases(_edit_and_unassign_reach_gh_as_issue_edit),
    *_cases(_roadmap_and_area_fields_are_set_on_the_card),
    *_cases(_nothing_on_the_board_can_be_deleted),
    *_cases(_the_kill_switch_still_refuses_everyone),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_gh_read_reaches_the_model_whole_or_as_failed_names_owner_and_filter_and_deletes_nothing(scenario, given, uses, request):
    """A gh read reaches the model as failed when gh fails, keeps the newest comment under the budget, names each issue's owner and the filter that ran, and nothing on the board can be deleted: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
