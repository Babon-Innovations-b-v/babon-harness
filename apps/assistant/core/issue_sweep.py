"""Orphan-issue sweep, keep every open issue either a PRD or part of one
(workflow/loop).

The team also opens issues from GitHub's own "New issue" button, outside
Claude, and those miss a PRD-parent (the enforcement in `to-prd` and the
`issue_guard` hook only fire on the Claude path). GitHub can't hard-block that
button without a GitHub Action, and Actions are banned here, so
the assistant closes the gap after the fact on its patrol beat.

Area-aware: the backlog belongs to the first area in project.json, so only an
orphan whose area label is that one (or missing) is adopted under it, as a native
sub-issue with a creator ping, and the sweep then guarantees an assignee
(creator when the assistant knows their login, else the repository owner). An orphan
labelled for another area is NOT adopted: it gets the `needs-parent`
label plus one ping asking its creator to nest it under that area's
PRD; the label makes the flagging once-only.

Deterministic, not a judgement: a real orphan is always adopted or flagged,
never "maybe". Open issues are READ with the read token; every WRITE goes
through `github_act`, so its kill switch (`ASSISTANT_GITHUB_WRITE`), write token,
and audit log all apply, turn the flag off and the sweep goes quiet with the
rest of the assistant's writes.

Idempotent by construction: adopting sets the parent and flagging sets the
label, so the next sweep no longer sees the issue. Each orphan is swept, and
pinged, once.

Single public callable: ``sweep_orphan_issues()``.

FAILURE POLICY: Tier-2, a read or per-issue write fault is logged and the
sweep moves on; a broken sweep must never take the patrol beat down.
"""
from __future__ import annotations

from apps.assistant.shared.project import AREA_LABEL_PREFIX, AREAS, BACKLOG_PRD, GITHUB_REPO, OWNER_LOGIN

import json
import logging
import os
import subprocess

from apps.assistant.core.tools.gh import github_act

log = logging.getLogger("openclaw.issue_sweep")

_REPO = GITHUB_REPO
_OWNER, _NAME = _REPO.split("/")
# The standing backlog issue from project.json's `backlog_prd`; loose issues of
# the first area (or every loose issue when the board has no areas) land here.
# Orphans labelled for another area are flagged, never adopted here. No
# backlog configured means the sweep does nothing.
_BACKLOG = BACKLOG_PRD
_PRD_LABEL = "PRD"
_AREA_PREFIX = AREA_LABEL_PREFIX
_BACKLOG_AREA = AREAS[0] if AREAS else None
# Once-only marker for a non-dev orphan: carrying it means the creator was
# already pinged to nest it under their area's PRD.
_NEEDS_PARENT_LABEL = "needs-parent"
# The repository owner; the assignee fallback when a creator's login is unknown.
_FALLBACK_ASSIGNEE = OWNER_LOGIN
# Same kill switch as every the assistant write: off = the sweep reads nothing, writes
# nothing (github_act would refuse anyway; short-circuit so we don't even list).
_ENABLE_ENV = "ASSISTANT_GITHUB_WRITE"
_PAGE = 100
_MAX_PAGES = 20  # backstop: 2000 open issues is far past anything real
_TIMEOUT_S = 30


def _list_open_issues() -> list[dict]:
    """Every open issue with the three fields the orphan test needs: its
    number, its labels, and whether it already has a parent. Paginated GraphQL
    (REST issue-list can't return the sub-issue parent). Author login rides
    along for the ping."""
    nodes: list[dict] = []
    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        after = f', after:"{cursor}"' if cursor else ""
        query = (
            f'query{{repository(owner:"{_OWNER}",name:"{_NAME}")'
            f'{{issues(first:{_PAGE},states:OPEN{after})'
            f'{{pageInfo{{hasNextPage endCursor}}'
            f' nodes{{number author{{login}} labels(first:30){{nodes{{name}}}}'
            f' assignees(first:5){{nodes{{login}}}}'
            f' parent{{number}}}}}}}}}}'
        )
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=_TIMEOUT_S, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh graphql failed: {result.stderr.strip()[:200]}")
        issues = (
            (json.loads(result.stdout or "{}").get("data") or {})
            .get("repository", {})
            .get("issues", {})
        )
        nodes.extend(issues.get("nodes") or [])
        page = issues.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return nodes


def _is_orphan(node: dict) -> bool:
    """A loose issue: not the backlog itself, not a PRD epic, and not already
    nested under a parent. Everything else is 'part of one' and left alone."""
    if int(node.get("number", 0)) == _BACKLOG:
        return False
    labels = {label["name"] for label in (node.get("labels") or {}).get("nodes", [])}
    if _PRD_LABEL in labels:
        return False
    if node.get("parent"):
        return False
    return True


def _area(node: dict) -> str | None:
    """The issue's area from its `area:<x>` label, or None."""
    for label in (node.get("labels") or {}).get("nodes", []):
        name = str(label.get("name", ""))
        if name.startswith(_AREA_PREFIX):
            return name[len(_AREA_PREFIX):]
    return None


def _labels(node: dict) -> set[str]:
    return {label["name"] for label in (node.get("labels") or {}).get("nodes", [])}


def _ping_body(login: str) -> str:
    """The one comment left on an adopted issue: name the creator so they get a
    notification (workflow rule: address people by @handle), say what happened,
    and invite them to move it if it belongs under another PRD."""
    who = f"@{login} " if login else ""
    return (
        f"{who}this issue was loose, so I nested it as a sub-issue under the "
        f"backlog #{_BACKLOG}. Belongs under another PRD? "
        f"Feel free to move it."
    )


def _dept_ping_body(login: str, area: str) -> str:
    """The one comment left on a flagged non-dev orphan: the dev-backlog is the
    wrong home (a task in another area belongs under that area's own PRD), so
    ask the creator to nest it there."""
    who = f"@{login} " if login else ""
    return (
        f"{who}this issue is labelled `{_AREA_PREFIX}{area}` and has no parent "
        f"PRD. The backlog #{_BACKLOG} is for the {_BACKLOG_AREA} area, so I didn't adopt it; "
        f"I tagged it `{_NEEDS_PARENT_LABEL}` instead. Please nest it under "
        f"the {area} PRD it belongs to."
    )


def _flag_needs_parent(number: int, login: str, area: str) -> bool:
    """Label a non-dev orphan `needs-parent` and ping its creator once. The
    label lands first: if it fails the issue is retried next sweep, and once it
    sticks the orphan is never flagged again."""
    labelled = github_act.execute(
        {"action": "label", "issue_number": number,
         "add_labels": [_NEEDS_PARENT_LABEL]},
        actor="assistant",
    )
    if not labelled.startswith("done:"):
        log.warning("flag #%s did not complete: %s", number, labelled)
        return False
    pinged = github_act.execute(
        {"action": "comment", "issue_number": number,
         "body": _dept_ping_body(login, area)},
        actor="assistant",
    )
    if not pinged.startswith("done:"):
        log.warning("flag ping #%s did not complete: %s", number, pinged)
    return True


def _ensure_assignee(node: dict, number: int, login: str) -> None:
    """Every issue carries an assignee. An adopted orphan without
    one gets its creator when the assistant knows that login, else the repository owner."""
    if (node.get("assignees") or {}).get("nodes"):
        return
    for candidate in (login, _FALLBACK_ASSIGNEE):
        if not candidate:
            continue
        result = github_act.execute(
            {"action": "assign", "issue_number": number, "assignee": candidate},
            actor="assistant",
        )
        if result.startswith("done:"):
            return
    log.warning("could not ensure an assignee on #%s", number)


def sweep_orphan_issues() -> list[int]:
    """Adopt every open dev/unlabeled orphan under the backlog PRD
    (ping + guaranteed assignee), and flag every non-dev orphan with
    `needs-parent` + a ping instead. Returns the numbers actually
    adopted this pass (empty when the kill switch is off, the listing failed,
    or there were no orphans)."""
    if _BACKLOG is None:
        log.info("issue sweep skipped: no backlog_prd in .claude/project.json")
        return []
    if os.environ.get(_ENABLE_ENV) != "1":
        log.info("issue sweep skipped: %s is off", _ENABLE_ENV)
        return []
    try:
        nodes = _list_open_issues()
    except Exception as exc:  # noqa: BLE001, Tier-2: never break the patrol beat
        log.warning("issue sweep listing failed: %s", exc)
        return []

    adopted: list[int] = []
    flagged: list[int] = []
    for node in nodes:
        try:
            if not _is_orphan(node):
                continue
            number = int(node["number"])
            login = ((node.get("author") or {}).get("login")) or ""
            area = _area(node)
            if area and _BACKLOG_AREA and area != _BACKLOG_AREA:
                if _NEEDS_PARENT_LABEL in _labels(node):
                    continue  # already flagged; a human moves it
                if _flag_needs_parent(number, login, area):
                    flagged.append(number)
                continue
            result = github_act.execute(
                {
                    "action": "adopt",
                    "issue_number": number,
                    "parent": _BACKLOG,
                    "body": _ping_body(login),
                },
                actor="assistant",
            )
            if result.startswith("done:"):
                adopted.append(number)
                _ensure_assignee(node, number, login)
            else:
                log.warning("adopt #%s did not complete: %s", number, result)
        except Exception as exc:  # noqa: BLE001, Tier-2: skip this issue, keep going
            log.warning("issue sweep item failed: %s", exc)

    if adopted:
        log.info("issue sweep adopted %s under #%s", adopted, _BACKLOG)
    if flagged:
        log.info("issue sweep flagged %s as %s", flagged, _NEEDS_PARENT_LABEL)
    return adopted
