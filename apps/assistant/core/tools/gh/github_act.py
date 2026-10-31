"""`github_act` tool, the assistant acts on the GitHub board on its own
initiative.

The assistant's read tools (`gh_issue_view` etc.) let it SEE the backlog; this
lets it DO the PA hygiene a good assistant would: comment, open an
issue for a gap it found, edit a title or body, assign or unassign,
add or remove labels, move a card or set its roadmap dates and
area, and close or reopen. One tool, an action enum (same shape
as `scw_read` / `manage_worklist`).

FULL BOARD WRITE, for the whole team: the assistant has full write access to
the board, because without it it cannot help. Anyone in the people registry
may drive a write, and the assistant may write on its own initiative. What the
action enum leaves out is the bound: nothing here deletes an issue or a
comment, and nothing touches a branch, a pull request, a secret or any
other repository, so every action it does have is one a person can undo.

THREE locks make "full initiative" safe:
  1. KILL SWITCH. Every write is refused unless ``ASSISTANT_GITHUB_WRITE=1``
     is set in the container env. Unset the flag and the assistant goes read-only
     instantly, no redeploy.
  2. WRITE TOKEN. Writes run ``gh`` with ``GITHUB_ASSISTANT_TOKEN`` (a
     write-scoped PAT, distinct from the read-only ``GH_TOKEN``), so
     The assistant's changes are attributable to its own identity and the read
     path stays least-privilege. If the write token is unset the tool
     refuses rather than silently falling back to a read token.
  3. AUDIT. Every action is recorded in ``state.assistant_actions`` BEFORE
     it is reported done, so there is always a durable log of what the
     assistant changed. Everything here is reversible on GitHub
     (reopen, re-assign, edit back, delete-comment), and the log is how
     you find and undo a bad one.

Scope is hardcoded to ``the project repository``, the assistant cannot
touch any other repo. Board conventions it must honour (also in its
principles): a NEW issue always gets an assignee at creation
(workflow rule, the owner); epics carry the PRD label.

Tool-module grammar: ``NAME``, ``DEFINITION``, ``execute``.

FAILURE POLICY: Tier-2 in the loop's dispatch (a refusal/`gh` error
returns as text to the LLM); the `state.record_action` audit write is
Tier-1 (propagates, an unrecordable action is not taken).
"""
from __future__ import annotations

from apps.assistant.shared.project import AREA_LABEL_PREFIX, AREAS, GITHUB_REPO, PEOPLE

import json
import os
import re
import subprocess
from typing import Any

from apps.assistant.core import people
from apps.assistant.core.tools import write_guard

NAME = "github_act"
_REPO = GITHUB_REPO
# The one the project board (GitHub Projects V2); its Status column is a single-select
# field, NOT an issue label, moving a card to Review means setting that field.
_PROJECT_NUMBER = 1
_ENABLE_ENV = "ASSISTANT_GITHUB_WRITE"
_WRITE_TOKEN_ENV = "GITHUB_ASSISTANT_TOKEN"
# Who may DRIVE a board write: the assistant on its own initiative (actor "assistant"),
# or anyone the people registry holds. A name the registry
# does not hold is refused, so the audit row always names a teammate or the assistant.
_SELF_ACTOR = "assistant"
# The board fields `field` may set, by their name on project #1. Status has
# its own action; these are the roadmap and swimlane fields `to-prd` sets.
_SETTABLE_FIELDS = ("Roadmap start", "Roadmap end", "Area")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMEOUT_S = 30

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Act on the GitHub board (the project repository): comment; create "
        "(title, assignee, and add_labels with one area label when the board "
        "has areas, plus bug, enhancement or PRD; a small loose task nests under "
        "the backlog issue); adopt (nest an "
        "issue under `parent`); edit; assign; unassign (never leave an open "
        "issue with nobody); label; status (the board column, not a label); "
        "field; close (with a one-line comment why); reopen. Nothing can be "
        "deleted. Close only what is done, open only a real gap; when in doubt, "
        "ask."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "comment", "create", "edit", "adopt", "assign", "unassign",
                    "label", "status", "field", "close", "reopen",
                ],
            },
            "issue_number": {
                "type": "integer",
                "description": "Not for create.",
            },
            "status": {
                "type": "string",
                "description": (
                    "Column, e.g. 'Review', 'In Progress', 'Done', 'Not "
                    "started', 'LowPriority'."
                ),
            },
            "body": {
                "type": "string",
                "description": "Comment text, or issue body for create/edit.",
            },
            "field": {
                "type": "string",
                "enum": list(_SETTABLE_FIELDS),
                "description": "Board field.",
            },
            "value": {
                "type": "string",
                "description": "YYYY-MM-DD for a Roadmap date, or the area name.",
            },
            "title": {"type": "string", "description": "Issue title."},
            "parent": {
                "type": "integer",
                "description": "Parent issue number to nest under.",
            },
            "assignee": {
                "type": "string",
                "description": "GitHub login. Required for create.",
            },
            "add_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to add.",
            },
            "remove_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to remove.",
            },
        },
        "required": ["action"],
    },
}


_refuse = write_guard.refuse


def _may_drive(actor: str) -> bool:
    """True when the driver is the assistant itself or someone the people registry
    holds, by name and case-insensitive (the owner: the whole team)."""
    wanted = actor.strip().lower()
    if wanted == _SELF_ACTOR:
        return True
    return any(name.lower() == wanted for name in people.names())


def _gh(args: list[str], token: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GH_TOKEN"] = token  # write-scoped identity for this call
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=_TIMEOUT_S,
        env=env, check=False,
    )


def _num(tool_input: dict) -> str:
    return str(int(tool_input["issue_number"]))


# Team GitHub logins, from `people` in `.claude/project.json` (display name ->
# login). The assistant knows people by name (the people registry); the board
# needs the login, and gh SILENTLY drops an unknown --assignee (the issue is
# created with no assignee and the call still succeeds), so a guessed login
# looks like it worked but leaves the issue unassigned. Resolve the name to the
# real login here, and refuse an unknown name so it is corrected instead of
# guessed. A new collaborator is one entry in project.json.
_GH_LOGINS = {name.lower(): login for name, login in PEOPLE.items()}
_KNOWN_LOGINS = {login.lower(): login for login in _GH_LOGINS.values()}


def _resolve_assignee(assignee: str) -> str | None:
    """A team name ('the owner') or a login ('alex-example') -> the canonical login,
    or None if unknown. Case-insensitive."""
    key = assignee.strip().lower()
    return _GH_LOGINS.get(key) or _KNOWN_LOGINS.get(key)


_ASSIGNEE_HELP = (
    "assign one of: " + ", ".join(PEOPLE) + " (by name is fine)."
    if PEOPLE else "assign a GitHub login listed under people in .claude/project.json."
)

# The issue contract `.claude/hooks/issue_guard.py` enforces on the Claude
# path; that hook does not run in the container, so `create` mirrors it here:
# every issue needs an area label (when the board declares areas) and either
# PRD or a category.
_AREAS = AREAS
_PRD_LABEL = "PRD"
_CATEGORY_LABELS = (_PRD_LABEL, "bug", "enhancement")


#: A root PRD has to say which open roots it was weighed against.
#: `.claude/hooks/issue_guard.py` refuses one without this section on the
#: Claude path; that hook cannot run in this pod, so the same rule is applied
#: here. It matters because the assistant opens roots on its own when a
#: meeting introduces a subject the board has no root for, and an unchecked
#: root is how one subject ends up with several competing roots.
_ROOT_CHECK_HEADING = "## root check"


def _missing_root_check(labels: list[str], parent: Any, body: str) -> str | None:
    """The refusal when a new ROOT carries no root check, else None.

    Only a PRD with no parent is a root. A PRD nested under something is not
    a root and the board does not show a third layer of them anyway, which
    `_missing_create_labels` leaves to the caller's own judgement.
    """
    if _PRD_LABEL not in labels or _parent_number(parent) is not None:
        return None
    if _ROOT_CHECK_HEADING in (body or "").lower():
        return None
    return (
        "a new root PRD needs a '## Root check' section in its body naming the "
        "open roots you weighed it against and why none of them covers it "
        "One subject gets one root; without that section the "
        "repository refuses it anyway."
    )


def _missing_create_labels(labels: list[str]) -> str | None:
    """The refusal message when `create` labels break the issue contract, or
    None when they satisfy it."""
    if _AREAS and not any(
        label.startswith(AREA_LABEL_PREFIX) and label[len(AREA_LABEL_PREFIX):] in _AREAS
        for label in labels
    ):
        return (
            "create needs an area label in add_labels: "
            f"{AREA_LABEL_PREFIX}<" + "|".join(_AREAS) + "> (the board sorts on it)"
        )
    if not any(label in _CATEGORY_LABELS for label in labels):
        return (
            "create needs a category label in add_labels: "
            + ", ".join(_CATEGORY_LABELS)
        )
    return None


def _parent_number(raw: Any) -> int | None:
    """A parent issue reference ('151', '#151', 151) -> the int, or None."""
    try:
        return int(str(raw).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None


def _issue_number_from_url(stdout: str) -> str | None:
    """`gh issue create` prints the new issue URL; pull its trailing number."""
    tail = stdout.strip().rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


def issue_number_in(result: str) -> int | None:
    """The issue number in an `execute()` result, or None.

    `execute` returns prose with the `gh` stdout on the end, and for `create`
    that stdout is the new issue's URL. A caller that has to DO something with
    the issue it just opened (nest it, record it, name it once) would otherwise
    re-parse that prose itself, so the parse lives here with the format it
    depends on.
    """
    match = re.search(r"/issues/(\d+)\b", result or "")
    return int(match.group(1)) if match else None


def _nest_under_parent(parent_num: int, child_number: str, token: str) -> str:
    """Create the NATIVE GitHub sub-issue link parent -> child, so the child
    nests under the parent on the board (and fills its Sub-issues progress bar)
    instead of floating as a loose top-level card. gh silently leaves a new
    issue un-nested when you only name the parent in the body, so we make the
    relationship for real. The sub_issues API keys on the child's database id,
    not its number. Best-effort: returns a short note either way (a failed nest
    must not undo a created issue)."""
    got = _gh(["api", f"repos/{_REPO}/issues/{child_number}", "--jq", ".id"], token)
    child_db_id = got.stdout.strip()
    if got.returncode != 0 or not child_db_id.isdigit():
        return f"could not nest under #{parent_num} (no issue id)"
    linked = _gh(["api", "--method", "POST",
                  f"repos/{_REPO}/issues/{parent_num}/sub_issues",
                  "-F", f"sub_issue_id={child_db_id}"], token)
    if linked.returncode != 0:
        return f"nest under #{parent_num} failed: {linked.stderr.strip()[:120]}"
    return f"nested under #{parent_num}"


def _fail(message: str) -> subprocess.CompletedProcess:
    """A synthetic failed result so the common error tail reports it."""
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=message)


def _board_field(num: str, field_name: str, value: str, token: str) -> subprocess.CompletedProcess:
    """Set one board field (Projects V2) on an issue's card: a single-select
    such as Status or Area, by option name, or a date such as Roadmap
    start, as YYYY-MM-DD. Resolves the issue's project item and the field by
    name, then mutates. Returns the mutation result, or a synthetic failure
    when the issue is not on the board, the field is unknown, or the value
    fits no option. Mirrors `.claude/scripts/board-status.py`."""
    owner, name = _REPO.split("/")
    query = (
        f'query{{repository(owner:"{owner}",name:"{name}")'
        f'{{issue(number:{int(num)}){{projectItems(first:10){{nodes{{id project{{id number}}}}}}}}}}'
        f' organization(login:"{owner}"){{projectV2(number:{_PROJECT_NUMBER})'
        f'{{field(name:{json.dumps(field_name)})'
        f'{{... on ProjectV2SingleSelectField{{id dataType options{{id name}}}}'
        f' ... on ProjectV2Field{{id dataType}}}}}}}}}}'
    )
    lookup = _gh(["api", "graphql", "-f", f"query={query}"], token)
    if lookup.returncode != 0:
        return lookup
    data = json.loads(lookup.stdout or "{}").get("data") or {}
    issue = (data.get("repository") or {}).get("issue") or {}
    items = (issue.get("projectItems") or {}).get("nodes") or []
    item = next((node for node in items if node["project"]["number"] == _PROJECT_NUMBER), None)
    field = ((data.get("organization") or {}).get("projectV2") or {}).get("field") or {}
    if item is None:
        return _fail(f"#{num} is not on board project #{_PROJECT_NUMBER}")
    if not field.get("id"):
        return _fail(f"could not read the board {field_name} field")
    if field.get("dataType") == "DATE":
        if not _DATE_RE.match(value):
            return _fail(f"{field_name} needs a date as YYYY-MM-DD, not {value!r}")
        field_value = f'{{date:"{value}"}}'
    else:
        wanted = value.lower().removeprefix(AREA_LABEL_PREFIX)
        option = next(
            (opt for opt in field.get("options", []) if opt["name"].lower() == wanted),
            None,
        )
        if option is None:
            names = ", ".join(opt["name"] for opt in field.get("options", []))
            return _fail(f"unknown {field_name} {value!r}; the board has: {names}")
        field_value = f'{{singleSelectOptionId:"{option["id"]}"}}'
    mutation = (
        f'mutation{{updateProjectV2ItemFieldValue(input:{{projectId:"{item["project"]["id"]}",'
        f'itemId:"{item["id"]}",fieldId:"{field["id"]}",'
        f'value:{field_value}}}){{projectV2Item{{id}}}}}}'
    )
    return _gh(["api", "graphql", "-f", f"query={mutation}"], token)


_DEFAULT_STATUS = "Not started"


def _ensure_on_board(num: str, token: str) -> str:
    """Make an adopted issue board-complete: on project #1 (adding it
    when GitHub's auto-add missed it) with a Status, defaulting an empty
    Status to 'Not started' and never overwriting a set one. Best-effort:
    returns a short note either way, a board fault must not undo the nest."""
    owner, name = _REPO.split("/")
    query = (
        f'query{{repository(owner:"{owner}",name:"{name}")'
        f'{{issue(number:{int(num)}){{id projectItems(first:10){{nodes{{id'
        f' project{{id number}}'
        f' fieldValueByName(name:"Status")'
        f'{{... on ProjectV2ItemFieldSingleSelectValue{{name}}}}}}}}}}}}'
        f' organization(login:"{owner}"){{projectV2(number:{_PROJECT_NUMBER})'
        f'{{id field(name:"Status"){{... on ProjectV2SingleSelectField{{id options{{id name}}}}}}}}}}}}'
    )
    lookup = _gh(["api", "graphql", "-f", f"query={query}"], token)
    if lookup.returncode != 0:
        return f"board sync failed: {lookup.stderr.strip()[:120]}"
    data = json.loads(lookup.stdout or "{}").get("data") or {}
    issue = (data.get("repository") or {}).get("issue") or {}
    project = (data.get("organization") or {}).get("projectV2") or {}
    field = project.get("field") or {}
    if not (issue.get("id") and project.get("id") and field.get("id")):
        return "board sync failed: could not read issue/project/Status"
    items = (issue.get("projectItems") or {}).get("nodes") or []
    item = next((node for node in items if node["project"]["number"] == _PROJECT_NUMBER), None)
    if item is None:
        added = _gh(["api", "graphql", "-f", "query="
                     f'mutation{{addProjectV2ItemById(input:{{projectId:"{project["id"]}",'
                     f'contentId:"{issue["id"]}"}}){{item{{id}}}}}}'], token)
        if added.returncode != 0:
            return f"board add failed: {added.stderr.strip()[:120]}"
        item_id = ((json.loads(added.stdout or "{}").get("data") or {})
                   .get("addProjectV2ItemById", {}).get("item") or {}).get("id")
        if not item_id:
            return "board add failed: no item id returned"
        note = "added to board"
    else:
        if (item.get("fieldValueByName") or {}).get("name"):
            return "already on board"
        item_id = item["id"]
        note = "on board"
    option = next(
        (opt for opt in field.get("options", [])
         if opt["name"].lower() == _DEFAULT_STATUS.lower()),
        None,
    )
    if option is None:
        return f"{note}; no {_DEFAULT_STATUS!r} column"
    moved = _gh(["api", "graphql", "-f", "query="
                 f'mutation{{updateProjectV2ItemFieldValue(input:{{projectId:"{project["id"]}",'
                 f'itemId:"{item_id}",fieldId:"{field["id"]}",'
                 f'value:{{singleSelectOptionId:"{option["id"]}"}}}}){{projectV2Item{{id}}}}}}'],
                token)
    if moved.returncode != 0:
        return f"{note}; status set failed: {moved.stderr.strip()[:120]}"
    return f"{note}, status {_DEFAULT_STATUS}"


def execute(tool_input: dict, actor: str = "assistant") -> str:
    disabled = write_guard.require_enabled(_ENABLE_ENV, "change the board")
    if disabled:
        return disabled
    token = os.environ.get(_WRITE_TOKEN_ENV, "").strip()
    if not token:
        return _refuse(f"{_WRITE_TOKEN_ENV} not set, no write-scoped GitHub token wired")

    # The assistant's own initiative and every teammate in the registry may drive a
    # write; a name the registry does not hold may not.
    if not _may_drive(actor):
        return _refuse(
            f"{actor} is not in my people registry, so I can't make board "
            f"changes on their behalf. I can look and suggest."
        )

    action = str(tool_input.get("action", "")).strip()
    try:
        if action == "comment":
            body = str(tool_input.get("body", "")).strip()
            if not body:
                return "comment needs a body"
            num = _num(tool_input)
            result = _gh(["issue", "comment", num, "--repo", _REPO, "--body", body], token)
            target, summary = f"issue #{num}", f"commented: {body[:80]}"
        elif action == "create":
            title = str(tool_input.get("title", "")).strip()
            assignee = str(tool_input.get("assignee", "")).strip()
            if not title:
                return "create needs a title"
            if not assignee:
                return "create needs an assignee (hard team rule: every issue gets one at creation)"
            login = _resolve_assignee(assignee)
            if login is None:
                return f"I don't have a GitHub login for {assignee!r}; {_ASSIGNEE_HELP}"
            labels_in = [str(label) for label in tool_input.get("add_labels", []) or []]
            contract_gap = _missing_create_labels(labels_in)
            if contract_gap:
                return contract_gap
            root_gap = _missing_root_check(
                labels_in, tool_input.get("parent"), str(tool_input.get("body", ""))
            )
            if root_gap:
                return root_gap
            args = ["issue", "create", "--repo", _REPO, "--title", title,
                    "--body", str(tool_input.get("body", "")).strip() or title,
                    "--assignee", login]
            for label in labels_in:
                args += ["--label", label]
            result = _gh(args, token)
            target, summary = "new issue", f"created {title[:80]!r} for {login}"
            parent_num = _parent_number(tool_input.get("parent"))
            if result.returncode == 0 and parent_num is not None:
                child_number = _issue_number_from_url(result.stdout)
                summary += "; " + (
                    _nest_under_parent(parent_num, child_number, token)
                    if child_number else f"could not nest under #{parent_num} (no number returned)"
                )
        elif action == "adopt":
            # Nest an EXISTING loose issue under a parent (the orphan sweep's
            # write). Same native sub-issue link as `create parent=…`,
            # but for an issue that already exists; the optional body pings the
            # creator. Best-effort ping: a failed comment must not undo the nest.
            num = _num(tool_input)
            parent_num = _parent_number(tool_input.get("parent"))
            if parent_num is None:
                return "adopt needs a parent issue number to nest under"
            note = _nest_under_parent(parent_num, num, token)
            if not note.startswith("nested under"):
                return f"gh adopt failed: {note}"
            summary = f"adopted #{num} under #{parent_num}"
            body = str(tool_input.get("body", "")).strip()
            if body:
                pinged = _gh(["issue", "comment", num, "--repo", _REPO, "--body", body], token)
                summary += "; pinged creator" if pinged.returncode == 0 else "; ping failed"
            summary += f"; {_ensure_on_board(num, token)}"
            result = subprocess.CompletedProcess(args=[], returncode=0, stdout=note, stderr="")
            target = f"issue #{num}"
        elif action == "assign":
            assignee = str(tool_input.get("assignee", "")).strip()
            if not assignee:
                return "assign needs an assignee"
            login = _resolve_assignee(assignee)
            if login is None:
                return f"I don't have a GitHub login for {assignee!r}; {_ASSIGNEE_HELP}"
            num = _num(tool_input)
            result = _gh(["issue", "edit", num, "--repo", _REPO, "--add-assignee", login], token)
            target, summary = f"issue #{num}", f"assigned to {login}"
        elif action == "unassign":
            assignee = str(tool_input.get("assignee", "")).strip()
            if not assignee:
                return "unassign needs the assignee to take off"
            login = _resolve_assignee(assignee)
            if login is None:
                return f"I don't have a GitHub login for {assignee!r}; {_ASSIGNEE_HELP}"
            num = _num(tool_input)
            result = _gh(["issue", "edit", num, "--repo", _REPO, "--remove-assignee", login], token)
            target, summary = f"issue #{num}", f"unassigned {login}"
        elif action == "edit":
            num = _num(tool_input)
            title = str(tool_input.get("title", "")).strip()
            body = str(tool_input.get("body", "")).strip()
            if not (title or body):
                return "edit needs a new title and/or body"
            args = ["issue", "edit", num, "--repo", _REPO]
            if title:
                args += ["--title", title]
            if body:
                args += ["--body", body]
            result = _gh(args, token)
            changed = " and ".join(part for part, given in (("title", title), ("body", body)) if given)
            target, summary = f"issue #{num}", f"edited {changed}" + (f": {title[:80]!r}" if title else "")
        elif action == "field":
            num = _num(tool_input)
            field_name = str(tool_input.get("field", "")).strip()
            value = str(tool_input.get("value", "")).strip()
            wanted = next((known for known in _SETTABLE_FIELDS if known.lower() == field_name.lower()), None)
            if wanted is None:
                return "field needs one of: " + ", ".join(_SETTABLE_FIELDS)
            if not value:
                return f"field {wanted} needs a value"
            result = _board_field(num, wanted, value, token)
            target, summary = f"issue #{num}", f"board {wanted} -> {value}"
        elif action == "label":
            num = _num(tool_input)
            args = ["issue", "edit", num, "--repo", _REPO]
            for label in tool_input.get("add_labels", []) or []:
                args += ["--add-label", str(label)]
            for label in tool_input.get("remove_labels", []) or []:
                args += ["--remove-label", str(label)]
            if len(args) == 5:
                return "label needs add_labels and/or remove_labels"
            result = _gh(args, token)
            target, summary = f"issue #{num}", "relabelled"
        elif action == "close":
            num = _num(tool_input)
            body = str(tool_input.get("body", "")).strip()
            if body:
                _gh(["issue", "comment", num, "--repo", _REPO, "--body", body], token)
            result = _gh(["issue", "close", num, "--repo", _REPO], token)
            target, summary = f"issue #{num}", f"closed: {body[:80]}"
        elif action == "reopen":
            num = _num(tool_input)
            result = _gh(["issue", "reopen", num, "--repo", _REPO], token)
            target, summary = f"issue #{num}", "reopened"
        elif action == "status":
            num = _num(tool_input)
            status_name = str(tool_input.get("status", "")).strip()
            if not status_name:
                return "status needs a status value (e.g. 'Review', 'In Progress', 'Done')"
            result = _board_field(num, "Status", status_name, token)
            target, summary = f"issue #{num}", f"board status -> {status_name}"
        else:
            return f"unknown action: {action!r}"
    except (KeyError, ValueError):
        return f"{action} needs a valid issue_number"

    if result.returncode != 0:
        return f"gh {action} failed: {result.stderr[:300]}"
    # Tier-1 audit BEFORE reporting done.
    write_guard.audit(f"gh_{action}", target, summary, actor=actor,
                      detail=result.stdout[:300])
    return f"done: {summary} (logged). {result.stdout[:200]}".strip()
