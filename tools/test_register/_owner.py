"""Who a quarantined test belongs to, and what the gate tells them.

OWNS: resolving a row's owner to a GitHub login through `.claude/project.json`,
the issue the gate opens for a quarantined test, and the note a commit status
carries about what was quarantined.

DOES NOT OWN: opening the issue or posting the status (the gate step does, with
`gh`), the quarantine field itself (`_row.py`), or reading the project file
(`__main__.py` hands the parsed dict in).

THE OWNER. A row's `owner` is a name from `people` (mapped to its login) or a
login as written. A row naming nobody belongs to the project's `owner`. No
login is ever written here: they all come from the project file.

THE ISSUE. One per quarantined test, assigned to its owner, a sub-issue of
`backlog_prd`, labelled `bug` plus the area whose name is the test's first path
part when the project lists areas (the first area otherwise, because the issue
guard refuses an issue without one). The body says what failed and how the
quarantine ends: the owner deletes the `quarantined=` line in the commit that
fixes the test. There is no time limit, so the body names none.

THE NOTE. A commit status has a short description, so the note names each
quarantine's issue number before its file: cut short, the number survives and
the file name is what gets cut.

FAILURE POLICY. Pure: no I/O. A project file without people, owner, areas or a
backlog PRD gives an empty login, no area label or no parent, never an error.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

#: The longest issue body the gate writes, under the sub-issue cap.
BODY_LIMIT = 2800


def owner_login(row_owner: str, project: Mapping) -> str:
    """The GitHub login a row's owner resolves to; the project's owner when it names nobody."""
    people = project.get("people") or {}
    if row_owner:
        return str(people.get(row_owner, row_owner))
    return str(project.get("owner") or "")


def quarantine_issue(
    test: str, login: str, project: Mapping, *, commit: str, reason: str, failures: Sequence[str] = ()
) -> dict:
    """The issue for one quarantined test: title, body, assignee, labels and parent."""
    quoted = "\n".join(failures) or "(the red run named this file and no failing line)"
    body = (
        f"The deploy gate quarantined `{test}` at {commit[:12]}: it {reason}, so the red "
        f"was the test's fault and not the commit's. It is out of the gate until this is "
        f"fixed; every other test still gates every commit.\n\n"
        f"What failed:\n```\n{quoted}\n```\n\n"
        f"To end it: make the test check one purpose against a synthetic ground truth, and "
        f"delete its `quarantined=` line in `tools/test_register/_rows.py` in the same commit."
    )
    if len(body) > BODY_LIMIT:
        body = body[: BODY_LIMIT - 4] + "\n```"
    return {
        "title": f"test: {test.rsplit('/', 1)[-1]} is quarantined",
        "body": body,
        "assignee": login,
        "labels": ["bug", *_area_label(test, project)],
        "parent": project.get("backlog_prd"),
    }


def _area_label(test: str, project: Mapping) -> list[str]:
    """The one area label the issue carries, or none when the project lists no areas."""
    areas = [str(area) for area in project.get("areas") or []]
    if not areas:
        return []
    first_part = test.split("/", 1)[0]
    area = first_part if first_part in areas else areas[0]
    return [f"{project.get('area_label_prefix') or 'area:'}{area}"]


def quarantine_note(entries: Iterable[tuple[str, str]]) -> str:
    """`quarantined #<issue> <file>, ...` for a commit status, each issue before its file."""
    named = [f"{'#' + str(issue) + ' ' if issue else ''}{test.rsplit('/', 1)[-1]}" for issue, test in entries]
    return f"quarantined {', '.join(named)}" if named else ""
