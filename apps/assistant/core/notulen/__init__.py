"""What the assistant does with a set of corrected minutes.

The team fixes the minutes on the dashboard and presses one button; that
button is the approval, so nothing here asks again. The assistant reads the meeting,
finds the issues it touches, and writes to the board.

The split is the one the house rules already settled for pages: PYTHON
READS AND PYTHON WRITES, THE MODEL ONLY PICKS. The action points and the
decisions are parsed out of the markdown deterministically, the candidate
issues are read live off the board, and the model's single call chooses
where each item lands and writes the English wording. It cannot invent a
parent, a department or an assignee, because each of those is an enum closed
over what actually exists.

ONE TRAP. Every file here is named
after its one public callable and this seam re-exports that callable, so the
package attribute `file_minutes` IS the function, not the module. A caller
writing `from ...core.notulen import file_minutes as x` and then `x.file_minutes(...)`
imports clean, boots clean, and raises `AttributeError` the first time
somebody presses the button. Import the PACKAGE when you want the module
(`from apps.assistant.core import notulen`), or ask importlib for it by
name. `apps/assistant/tests/` checks that no route names something it
cannot call.

Module map (one public callable per file):
    parse_minutes.py:    parse_minutes(markdown) -> Minutes: the action items
                           table and the besluiten list, without a model
    candidate_issues.py: candidate_issues() -> list[Candidate]: the open
                           board, plus which of them are roots
    decide_placements.py, decide_placements(...) -> Placements | None: the one
                           judgement, as a closed-enum tool call
    file_minutes.py:     file_minutes(...) -> Filed: the orchestrator that
                           writes it all through `github_act`
"""
from __future__ import annotations

from apps.assistant.core.notulen.candidate_issues import (
    Candidate,
    candidate_issues,
)
from apps.assistant.core.notulen.decide_placements import (
    Placements,
    decide_placements,
)
from apps.assistant.core.notulen.file_minutes import Filed, file_minutes
from apps.assistant.core.notulen.parse_minutes import (
    Action,
    Minutes,
    parse_minutes,
)

__all__ = [
    "Action",
    "Candidate",
    "Filed",
    "Minutes",
    "Placements",
    "candidate_issues",
    "decide_placements",
    "file_minutes",
    "parse_minutes",
]
