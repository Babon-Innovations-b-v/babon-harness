"""Put a corrected meeting on the board.

The team pressed one button, so this asks nobody and writes. It is the
orchestrator and it holds no judgement of its own: `parse_minutes` says what
the meeting contains, `candidate_issues` says what exists, `decide_placements`
makes the single call that chooses, and everything from there is Python doing
what was chosen, in an order that fails safely.

THE ORDER MATTERS. A new root is opened first, because the action points that
asked for it need its number; then the action points; then the comments. Each
write is independent, and a failure part-way through leaves what already
landed rather than unwinding it: an issue that exists and is nested is worth
keeping, and there is no safe way to un-open work a person may already have
read.

Every write goes through `github_act`, so the kill switch
(`ASSISTANT_GITHUB_WRITE`), the write token and the audit row all apply. With the
switch off this files nothing and says so, which is what the button reports
back to the person who pressed it.

FAILURE POLICY: Tier-2 per item, one issue that will not open is logged and
the rest still land, because a meeting half-filed is better than a meeting
lost and the report says exactly what did not make it. The overall call
raises nothing.
"""
from __future__ import annotations

from apps.assistant.shared.project import AREAS, AREA_LABEL_PREFIX

import logging
from dataclasses import dataclass, field

from apps.assistant.core.notulen.candidate_issues import candidate_issues
from apps.assistant.core.notulen.decide_placements import (
    NEW_ROOT,
    decide_placements,
)
from apps.assistant.core.notulen.parse_minutes import parse_minutes
from apps.assistant.core.tools.gh import github_act

log = logging.getLogger("openclaw.notulen")

_CATEGORY_LABEL = "enhancement"
_PRD_LABEL = "PRD"


@dataclass
class Filed:
    """What actually reached the board, and what did not."""

    issues: list[int] = field(default_factory=list)
    root: int | None = None
    comments: list[int] = field(default_factory=list)
    #: Action points the board was already carrying, commented rather than
    #: opened again. Counted apart from `comments` because the two answer
    #: different questions: this one says how much of the meeting was already
    #: known, which is what tells you whether the board is keeping up.
    updated: list[int] = field(default_factory=list)
    #: Plain sentences about anything that did not land. This is the half the
    #: report leads with, because a silent partial file is the failure mode
    #: this whole path is built to avoid.
    problems: list[str] = field(default_factory=list)

    def as_report(self, title: str) -> str:
        """One short paragraph for Signal: what was opened, what was not."""
        parts = []
        if self.root:
            parts.append(f"opened root #{self.root}")
        if self.issues:
            parts.append("opened " + ", ".join(f"#{n}" for n in self.issues))
        if self.updated:
            parts.append(
                "already on the board, so updated rather than opened: "
                + ", ".join(f"#{n}" for n in self.updated)
            )
        if self.comments:
            parts.append("commented on " + ", ".join(f"#{n}" for n in self.comments))
        did = "; ".join(parts) if parts else "put nothing on the board"
        note = (" " + " ".join(self.problems)) if self.problems else ""
        return f"Filed the minutes of {title}: {did}.{note}"



def _area_labels(area: str) -> list[str]:
    """The area label for `area`, or none when the board declares no areas."""
    return [f"{AREA_LABEL_PREFIX}{area}"] if AREAS and area in AREAS else []

def file_minutes(
    job_id: str,
    title: str,
    meeting_date: str,
    markdown: str,
    minutes_url: str,
) -> Filed:
    """Read the meeting, decide where everything goes, and write it."""
    minutes = parse_minutes(markdown, title=title, meeting_date=meeting_date)
    if minutes.is_empty:
        return Filed(problems=["There were no action points and no decisions in it."])

    candidates = candidate_issues()
    if not candidates:
        return Filed(problems=[
            "I could not read the board, so I filed nothing rather than "
            "guessing at parents."
        ])

    placements = decide_placements(minutes, candidates)
    if placements is None:
        return Filed(problems=[
            "I could not work out where the items belong, so nothing was filed. "
            "The minutes are safe; press send again later."
        ])

    # Anything the plan named that was not on offer is dropped before a
    # single write, and said out loud: the item is still in the minutes and
    # nowhere else, so a silent drop is the worst of the outcomes.
    filed = Filed(problems=list(placements.refused))
    root = _open_root(placements, minutes, minutes_url, filed)
    _open_actions(placements, root, minutes_url, filed)
    _leave_comments(placements, minutes_url, filed)
    log.info(
        "filed minutes for job %s: root=%s issues=%s comments=%s problems=%s",
        job_id, filed.root, filed.issues, filed.comments, len(filed.problems),
    )
    return filed


def _open_root(placements, minutes, minutes_url: str, filed: Filed) -> int | None:
    """Open the new root, if the meeting introduced a subject that needs one.

    A root is a PRD, and the repository refuses a PRD whose body carries no
    `## Root check` section. The hook that enforces that does not
    run in this pod, so the section is written here from what the model
    named, and a plan that asked for a root without one is refused rather
    than sent to be rejected on the other side.
    """
    wants_root = any(
        action.get("parent") == NEW_ROOT for action in placements.actions
    )
    if not wants_root:
        return None
    spec = placements.new_root
    if not spec or not spec.get("root_check"):
        filed.problems.append(
            "Some items needed a new root and I could not write its root "
            "check, so I left those out; they are still in the minutes."
        )
        return None

    body = (
        f"## Root check\n{spec['root_check']}\n\n"
        f"## Goal\n{spec['goal']}\n\n"
        f"## Status\nOpened from the minutes of {minutes.title} "
        f"({minutes.meeting_date}), {minutes_url}\n\n"
        f"## Owner · Area · Horizon\n"
        f"{spec['assignee']} · {spec['area']} · now\n"
    )
    result = github_act.execute(
        {
            "action": "create",
            "title": spec["title"],
            "body": body,
            "assignee": spec["assignee"],
            "add_labels": _area_labels(spec["area"]) + [_PRD_LABEL],
        },
        actor="assistant",
    )
    number = github_act.issue_number_in(result)
    if number is None:
        filed.problems.append(f"I could not open the new root: {result[:160]}")
        return None
    filed.root = number
    return number


def _open_actions(placements, root: int | None, minutes_url: str, filed: Filed) -> None:
    """One issue per action point the board is not already carrying.

    An action point the board already has is commented, not opened again. That
    is the difference between a board and a pile: meetings repeat, a weekly one
    runs the same action point every week until it is done, and opening a card
    each time would buy ten owners for one task inside a fortnight.
    """
    for action in placements.actions:
        already = action.get("already")
        if already:
            _note_on_existing(int(already), action, minutes_url, filed)
            continue
        if not action.get("title") or not action.get("assignee"):
            filed.problems.append(
                "One action point came back neither as new work nor as "
                "something already on the board, so I left it off; it is still "
                "in the minutes."
            )
            continue
        parent = action.get("parent")
        if parent == NEW_ROOT:
            parent = root
        if not parent:
            filed.problems.append(
                f"No parent for \"{action.get('title', '')[:60]}\", so I left it off."
            )
            continue
        body = f"{action['body']}\n\nFrom the minutes: {minutes_url}"
        result = github_act.execute(
            {
                "action": "create",
                "title": action["title"],
                "body": body,
                "assignee": action["assignee"],
                "parent": int(parent),
                "add_labels": _area_labels(action["area"]) + [_CATEGORY_LABEL],
            },
            actor="assistant",
        )
        number = github_act.issue_number_in(result)
        if number is None:
            filed.problems.append(
                f"I could not open \"{action.get('title', '')[:60]}\": {result[:120]}"
            )
            continue
        filed.issues.append(number)


def _note_on_existing(
    number: int, action: dict, minutes_url: str, filed: Filed
) -> None:
    """Put the meeting's news on the issue that already carries this work.

    The comment says what the meeting said about it, and nothing else: the
    owner and the deadline on the issue are left alone, because a meeting
    saying a thing again is not the same as somebody deciding to move it, and
    a card silently re-owned by the last meeting to mention it is worse than
    one that is merely out of date.
    """
    body = action.get("body") or "This came up again in a meeting."
    result = github_act.execute(
        {
            "action": "comment",
            "issue_number": number,
            "body": f"{body}\n\nCame up again in the minutes: {minutes_url}",
        },
        actor="assistant",
    )
    if not result.startswith("done:"):
        filed.problems.append(
            f"This meeting repeated the work in #{number} and I could not "
            f"comment there: {result[:120]}"
        )
        return
    filed.updated.append(number)


def _leave_comments(placements, minutes_url: str, filed: Filed) -> None:
    """Each decision on the issue it touches. A decision is never an issue."""
    for comment in placements.comments:
        number = int(comment["issue"])
        result = github_act.execute(
            {
                "action": "comment",
                "issue_number": number,
                "body": f"{comment['body']}\n\nDecided in the meeting: {minutes_url}",
            },
            actor="assistant",
        )
        if not result.startswith("done:"):
            filed.problems.append(f"I could not comment on #{number}: {result[:120]}")
            continue
        filed.comments.append(number)
