"""The one judgement in this path: where each item from a meeting lands.

Everything around this file is deterministic. The action points and the
decisions were parsed in Python, the candidate issues were read off the live
board in Python, and the writing is done in Python. This is the single
bounded model call in between, and it is shaped the way `page_render` shapes
the page pick: every choice is an enum over something
that already exists, so the model picks and never invents.

WHAT IT MAY DECIDE. For each action point: whether the board already carries
it, and if not, an English title and body, which open issue it nests under
(or that a new root is needed), which department, and who owns it. For each
decision: which open issue it belongs on, or none.

THE ONE THAT KEEPS THE BOARD READABLE is that first question. A weekly
meeting carries the same action point week after week until it is done, and a
meeting often agrees to something the board has been tracking for a month.
Without somewhere to say "this is already an issue", every send opens another
card for it, and a fortnight of Mondays buys ten copies of the same task with
ten owners. So `already` is a field on every action point, and Python comments
the meeting's news onto that issue instead of opening anything.

WHAT IT MAY NOT, AND WHAT ACTUALLY STOPS IT. A tool-schema enum is guidance
to the model, not a rule the API enforces. A model can answer a parent that
is not a root, an issue carrying `enhancement` that sits under another, and
the cards would land as a fourth layer the board does not show. Enums without
checking is the mistake `page_render` names out loud: the enums can
only remove refusals, and the Python parse is the only enforcer.

So every choice is checked here against what was offered before anything is
written: the parent against the roots, the area against `.claude/project.json`, the
assignee against the team, an `already` or a comment against the open board.
Anything else is dropped and named in `refused`, which the caller reports.
It still cannot decide HOW MANY issues a meeting produces, because that came
out of the table, and it still has no field with which to make a decision
into an issue.

The minutes may be in another language than the board, so the wording it
writes is a translation, not a paste.

FAILURE POLICY: Tier-2, a budget trip, an outage or a malformed pick
returns None, and the caller reports that the meeting was not filed rather
than filing it badly. Half a meeting on the board is worse than none.
"""
from __future__ import annotations

from apps.assistant.shared.project import AREAS, OWNER_LOGIN, PEOPLE

import logging
from dataclasses import dataclass, field
from typing import Any

from apps.assistant.core import brain as _brain
from apps.assistant.core import self_context as _self_context
from apps.assistant.core.notulen.candidate_issues import Candidate
from apps.assistant.core.notulen.parse_minutes import Minutes

log = logging.getLogger("openclaw.notulen")

TOOL_NAME = "file_the_meeting"

#: The areas the board sorts on; `github_act` refuses anything else anyway.
AREA_NAMES = AREAS or ("general",)
#: Who can hold an issue. A Who in the minutes is a plain name and may be
#: somebody with no GitHub account at all (an outside partner in an intake
#: meeting), so the enum is the team plus the meeting's owner as the answer
#: for everyone else. The person's own name still goes in the body.
TEAM = tuple(PEOPLE) or ((OWNER_LOGIN,) if OWNER_LOGIN else ("owner",))

#: The model is asked to choose a parent, and this is what it says instead of
#: a number when a meeting opened a subject the board has no root for.
NEW_ROOT = 0

_TASK = """\
A meeting just happened and its minutes were corrected by the team. File it
on the board.

For every action point, ask FIRST whether the board is already carrying it.
Meetings repeat: a weekly one runs the same action point every week until it
is done, and a meeting often agrees to something already open. If an open
issue is that same piece of work, set `already` to its number and leave the
title, body, parent and the rest out. Nothing new is opened; the meeting's
news goes on that issue as a comment. Being about the same subject is not
enough, and neither is touching the same file: it has to be the same piece of
work, so that finishing one would finish the other.

An action point the board is NOT carrying becomes one issue. Write its title
and body in English even when the minutes are in another language: the board
is an engineering surface and the meeting's language stays in the minutes. Keep the
person's own name from the Who column in the body, and carry the deadline over
in words.

Choose the parent for each new one from the open issues listed. Prefer the
smallest thing that really covers it. Use 0 for the parent only when this
meeting opened a subject no open root covers at all, and then fill in the new
root; do not use it because a fit is imperfect.

Every decision belongs as a comment on the issue it touches. If a decision
touches no open issue, leave its issue out and say nothing about it: it is
recorded in the minutes already and does not need a card.

Opening nothing is a perfectly good answer. A meeting that only moved work
already on the board should leave it exactly as it found it, with comments.
"""


@dataclass(frozen=True)
class Placements:
    """The plan, ready for Python to execute. Checked, not straight off the call."""

    actions: list[dict[str, Any]]
    comments: list[dict[str, Any]]
    new_root: dict[str, Any] | None
    #: One plain sentence per choice that named something it was not offered.
    #: The caller reports these; a meeting that lost an item to a refusal has
    #: to say so, because the item is still in the minutes and nowhere else.
    refused: list[str] = field(default_factory=list)


def decide_placements(
    minutes: Minutes, candidates: list[Candidate]
) -> Placements | None:
    """Ask once where everything goes. None when the model could not answer."""
    if minutes.is_empty:
        return Placements(actions=[], comments=[], new_root=None)

    outcome = _brain.run(
        system=_self_context.render("notulen", _TASK),
        messages=[{"role": "user", "content": _render(minutes, candidates)}],
        tools=[tool_definition(minutes, candidates)],
        terminal_tools=frozenset({TOOL_NAME}),
        cap=1,
    )
    if not outcome.finished:
        log.warning("filing the meeting: brain unavailable (%s)", outcome.status)
        return None
    chosen = _tool_input(outcome.response)
    if chosen is None:
        log.warning("filing the meeting: no selection came back")
        return None
    return _only_what_was_offered(chosen, candidates)


def _only_what_was_offered(chosen: dict, candidates: list[Candidate]) -> Placements:
    """Drop every choice that named something outside what it was handed.

    This is the enforcer. The enums in the tool are what make a good answer
    likely; this is what makes a bad one harmless. A dropped item is named
    rather than silently lost, because it is still in the minutes and the
    person who pressed the button has to know it did not land.
    """
    roots = {candidate.number for candidate in candidates if candidate.is_root}
    open_issues = {candidate.number for candidate in candidates}
    refused: list[str] = []

    actions: list[dict[str, Any]] = []
    for action in chosen.get("actions") or []:
        name = str(action.get("title") or action.get("already") or "an action point")
        already = action.get("already")
        if already:
            if int(already) not in open_issues:
                refused.append(
                    f'"{name}" was said to be #{already} already, which is not '
                    "an open issue, so I left it off."
                )
                continue
            actions.append(action)
            continue
        parent = action.get("parent")
        if parent not in (NEW_ROOT, *roots):
            # A parent that is a child, not a root, would make a fourth layer
            # the board does not show.
            refused.append(
                f'"{name}" was to go under #{parent}, which is not one of the '
                "open roots, so I left it off."
            )
            continue
        if action.get("area") not in AREA_NAMES:
            refused.append(f'"{name}" named department {action.get("area")!r}.')
            continue
        if action.get("assignee") not in TEAM:
            refused.append(f'"{name}" named owner {action.get("assignee")!r}.')
            continue
        actions.append(action)

    comments: list[dict[str, Any]] = []
    for comment in chosen.get("comments") or []:
        if int(comment.get("issue") or 0) not in open_issues:
            refused.append(
                f"A decision was to go on #{comment.get('issue')}, which is not "
                "an open issue, so I left it off."
            )
            continue
        comments.append(comment)

    new_root = chosen.get("new_root") or None
    if new_root and (new_root.get("area") not in AREA_NAMES
                     or new_root.get("assignee") not in TEAM):
        refused.append("The new root named a department or owner that does not exist.")
        new_root = None

    return Placements(
        actions=actions, comments=comments, new_root=new_root, refused=refused,
    )


def tool_definition(minutes: Minutes, candidates: list[Candidate]) -> dict[str, Any]:
    """The pick, with every choice closed over what exists.

    Public because the schema IS the guarantee: a reader checking that the assistant
    cannot invent a parent should be able to read the enums without running
    the loop.
    """
    parents = [NEW_ROOT] + [c.number for c in candidates if c.is_root]
    commentable = [c.number for c in candidates]
    return {
        "name": TOOL_NAME,
        "description": (
            "File this meeting on the board. One entry in `actions` per action "
            "point, in the same order as the list you were given. One entry in "
            "`comments` per decision that belongs on an existing issue; leave "
            "out the decisions that belong nowhere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "maxItems": len(minutes.actions),
                    "items": {
                        "type": "object",
                        "properties": {
                            "already": {
                                "type": ["integer", "null"],
                                "enum": [None, *commentable],
                                "description": (
                                    "The open issue that IS this action point, "
                                    "when the board already carries it. Set it "
                                    "and leave everything else out: the meeting's "
                                    "news is commented there and nothing is "
                                    "opened. Null when this is new work."
                                ),
                            },
                            "title": {
                                "type": "string",
                                "description": (
                                    "English, imperative, under 70 characters. "
                                    "Leave out when `already` is set."
                                ),
                            },
                            "body": {
                                "type": "string",
                                "description": (
                                    "English. Say what has to happen and by when, "
                                    "and name the person the minutes named."
                                ),
                            },
                            "parent": {
                                "type": "integer",
                                "enum": parents,
                                "description": (
                                    "The open root this nests under, or 0 for a "
                                    "subject the board has no root for."
                                ),
                            },
                            "area": {"type": "string", "enum": list(AREA_NAMES)},
                            "assignee": {
                                "type": "string",
                                "enum": list(TEAM),
                                "description": (
                                    "The team member who owns it. When the minutes "
                                    "name somebody outside the team, pick the "
                                    "person from the team who is accountable for "
                                    "it and name the other person in the body."
                                ),
                            },
                        },
                        # Nothing is required, because an entry is one of two
                        # shapes: `already` alone, or a whole new issue. JSON
                        # Schema can express that as a choice, and the model
                        # then has to be right about which branch it is in;
                        # Python checking it afterwards is the same guarantee
                        # with a refusal a person can read. `file_minutes`
                        # rejects an entry that is neither and says which
                        # action point it left off, so a half-filled one costs
                        # a line in the report rather than a card with no
                        # title on it.
                        "required": [],
                    },
                },
                "comments": {
                    "type": "array",
                    "maxItems": len(minutes.decisions),
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue": {"type": "integer", "enum": commentable},
                            "body": {
                                "type": "string",
                                "description": (
                                    "English. The decision, and one line of why."
                                ),
                            },
                        },
                        "required": ["issue", "body"],
                    },
                },
                "new_root": {
                    "type": ["object", "null"],
                    "description": (
                        "Fill this in only when at least one action point has "
                        "parent 0. One root per subject."
                    ),
                    "properties": {
                        "title": {"type": "string"},
                        "goal": {
                            "type": "string",
                            "description": (
                                "Two or three plain sentences: why this exists "
                                "and what it delivers."
                            ),
                        },
                        "root_check": {
                            "type": "string",
                            "description": (
                                "Which open roots you looked at and why none of "
                                "them covers this. Name them by number. The "
                                "repository refuses a root without this."
                            ),
                        },
                        "area": {"type": "string", "enum": list(AREA_NAMES)},
                        "assignee": {"type": "string", "enum": list(TEAM)},
                    },
                    "required": ["title", "goal", "root_check", "area", "assignee"],
                },
            },
            "required": ["actions", "comments"],
        },
    }


def _render(minutes: Minutes, candidates: list[Candidate]) -> str:
    """The meeting and the board, as the model sees them."""
    lines = [f"Meeting: {minutes.title} ({minutes.meeting_date})", "", "Action points:"]
    for index, action in enumerate(minutes.actions, start=1):
        lines.append(
            f"{index}. {action.text} | Who: {action.who or 'unnamed'} | "
            f"Deadline: {action.deadline or 'none given'}"
        )
    lines += ["", "Decisions:"]
    for index, decision in enumerate(minutes.decisions, start=1):
        lines.append(f"{index}. {decision}")
    lines += ["", "Open issues on the board:"]
    lines += [candidate.as_line() for candidate in candidates]
    return "\n".join(lines)


def _tool_input(response: Any) -> dict | None:
    """The tool call's input, or None if the model answered with prose."""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") == "tool_use" and block.name == TOOL_NAME:
            return dict(block.input or {})
    return None
