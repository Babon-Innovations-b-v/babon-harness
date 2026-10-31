"""Pull the action items and the decisions out of a set of minutes.

No model runs here. The minutes are written to a template the notulen app
controls (`apps/notulen/inputs/notulen_template.md`), so what an action item
is, is a fact about the document rather than a judgement: a row in the
`## Action items` table with an Action, a Who and a Deadline. Reading it in
Python means the model is never the thing that decides how many issues a
meeting produces, which is the difference between a wrong word in an issue
title and a meeting that quietly opens eleven cards.

Each heading is matched against a short list of spellings, so a template
translated into another language keeps working once its heading is added
here.

FAILURE POLICY: Tier-2. A document that does not match the template yields
empty lists rather than raising. A meeting with no action items is a normal
meeting, and it must read the same as one whose table could not be found: in
both cases there is nothing to put on the board, and `file_minutes` says so
out loud rather than guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The two sections that carry work. Matched case-insensitively on a `##`
#: heading, so a stray `###` or a changed capital does not silently empty a
#: meeting.
_ACTIONS_HEADING = ("action items", "actions", "actiepunten")
_DECISIONS_HEADING = ("decisions", "besluiten")

_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
#: A numbered or bulleted decision line.
_DECISION_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)\s*$")
#: The table's own separator row, which is not a decision or an action.
_SEPARATOR = re.compile(r"^\s*\|[\s|:-]+\|\s*$")


@dataclass(frozen=True)
class Action:
    """One row of the action items table, as written."""

    text: str
    who: str
    deadline: str


@dataclass(frozen=True)
class Minutes:
    """A meeting, reduced to what can reach the board."""

    title: str
    meeting_date: str
    actions: list[Action] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when this meeting has nothing for the board. A real answer,
        not a failure: plenty of meetings decide nothing and assign nothing."""
        return not self.actions and not self.decisions


def parse_minutes(markdown: str, title: str = "", meeting_date: str = "") -> Minutes:
    """The action points and decisions in `markdown`.

    `title` and `meeting_date` are carried through from the job row rather
    than re-read from the document, because the row is what the dashboard
    and the board already agree on.
    """
    return Minutes(
        title=title,
        meeting_date=meeting_date,
        actions=_actions(_section(markdown, _ACTIONS_HEADING)),
        decisions=_decisions(_section(markdown, _DECISIONS_HEADING)),
    )


def _section(markdown: str, wanted: tuple[str, ...]) -> str:
    """The body under the first `## <heading>` whose text is one of `wanted`,
    up to the next `##`."""
    matches = list(_HEADING.finditer(markdown))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() not in wanted:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        return markdown[start:end]
    return ""


def _actions(section: str) -> list[Action]:
    """Table rows with something in the Action column.

    The template ships with one empty row, and a meeting with no action
    items leaves it there; a row whose action text is blank is that row,
    never a real one, so it is dropped rather than becoming an issue with an
    empty title.
    """
    actions: list[Action] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or _SEPARATOR.match(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        text = cells[0]
        # The header row names the columns; it is not an action.
        if not text or text.lower() in {"actie", "action"}:
            continue
        actions.append(Action(
            text=text,
            who=cells[1] if len(cells) > 1 else "",
            deadline=cells[2] if len(cells) > 2 else "",
        ))
    return actions


def _decisions(section: str) -> list[str]:
    """Numbered or bulleted lines under Decisions, minus the template's
    placeholder."""
    decisions: list[str] = []
    for line in section.splitlines():
        match = _DECISION_LINE.match(line)
        if not match:
            continue
        text = match.group(1).strip()
        if not text or text == "...":
            continue
        decisions.append(text)
    return decisions
