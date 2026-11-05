"""The minutes yield every action row and decision as written, and nothing from the template's placeholders.

WHAT IT PINS. `core.notulen.parse_minutes`, the step that decides how many
things a meeting puts on the board without a model: every row of the
`## Action items` table with text in its Action column, and every numbered or
bulleted line under `## Decisions`, both found case-insensitively and in either
language the template ships in, while the header row, the separator row, the
template's empty row, a row with a name but no action, and the `...`
placeholder are dropped.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The minutes
below are written here to the template's shape, and the expected rows and
decisions are copied out of them by hand.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row keeps a row
whose action text is blank, so Kim's row with no action becomes an action.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from apps.assistant.core.notulen.parse_minutes import Action, parse_minutes

MINUTES = """# Weekly

## Summary
We talked.

## action items
| Action | Who | Deadline |
|---|---|---|
| Send the quarter plan | Sam | Friday |
| Book the room | Robin | |
|  | Kim | Monday |
|  |  |  |

## Decisions
1. The plan goes out on Friday.
- Robin owns the room.
2. ...

## Next meeting
- not a decision
"""

DUTCH = """## Actiepunten
| Actie | Wie | Deadline |
|---|---|---|
| Offerte sturen | Kim | maandag |

## Besluiten
- We gaan door.
"""

CASES = [
    pytest.param(MINUTES, "actions",
                 [Action("Send the quarter plan", "Sam", "Friday"), Action("Book the room", "Robin", "")],
                 id="every-action-row-as-written"),
    pytest.param(MINUTES, "decisions", ["The plan goes out on Friday.", "Robin owns the room."],
                 id="every-decision-and-no-placeholder"),
    pytest.param(DUTCH, "actions", [Action("Offerte sturen", "Kim", "maandag")], id="the-dutch-template"),
    pytest.param(DUTCH, "decisions", ["We gaan door."], id="the-dutch-decisions"),
    pytest.param("# Notes\nNothing was decided.\n", "is_empty", True, id="a-meeting-with-nothing-for-the-board"),
]


@pytest.mark.parametrize("markdown, field, expected", CASES)
def test_the_minutes_yield_every_action_row_and_decision_as_written_and_nothing_from_the_template_placeholders(
        markdown: str, field: str, expected: object) -> None:
    """The parsed field is the one copied out by hand."""
    assert getattr(parse_minutes(markdown, "Weekly", "2026-05-04"), field) == expected
