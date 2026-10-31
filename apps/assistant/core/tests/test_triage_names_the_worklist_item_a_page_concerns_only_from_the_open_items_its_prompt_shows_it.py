"""Triage names the worklist item a page concerns only from the open items its prompt shows it.

WHAT IT PINS. `core.triage.triage` across its public interface: an alert goes
in, the model behind `core.brain.run` sees the user turn triage built, and the
`TriageResult` that comes back carries `worklist_items`, which the hold and the
chat relay pass on as the item a reply answers. The model can name an item
only from what it was shown, and an id that is not an open item is dropped.

WHY IT EXISTS. `submit_triage_decision` gained a `worklist_item` field, but
nothing triage read ever carried an item id, so the field could be filled only
by guessing, which its own description forbids. A page about an open
item would still have carried no id.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The model stub
holds no id of its own: it reads the id out of the user turn, from the line
that names the item whose title the alert is about, and submits that. Item 12
is written by hand as an open item of the owner's titled after the alert, so a turn
that shows it gives 12 and a turn that does not gives nothing. A stub that
names an id no open item has must come back with no item.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

_ALEX = "+15550100012"
_ITEM = 12
_TITLE = "example-api-key rotation guard is blind"


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh state DB with item 12 open, and a model stub that pages."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    from apps.assistant.core import brain, self_context, state, tools

    state.reset_for_tests()
    for number in range(1, _ITEM):
        state.worklist.add_item("look_into", f"unrelated item {number}", owner="Alex")
    state.worklist.add_item("look_into", _TITLE, owner="Alex")
    stub: dict[str, object] = {"override": None}

    def fake_run(*, messages, **_ignored):
        turn = str(messages[0]["content"])
        shown = re.search(rf"item (\d+): {re.escape(_TITLE)}", turn)
        named = int(shown.group(1)) if shown else None
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich",
                "reason": "rotation date missing",
                "signal_draft": "example-api-key has no rotation date, so its age alarm can never fire.",
                "worklist_item": stub["override"] if stub["override"] is not None else named,
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    return stub


def _triage(fingerprint: str):
    from apps.assistant.core.triage import Alert, triage

    return triage(Alert(
        fingerprint=fingerprint, status="firing",
        labels={"alertname": "TargetDown", "severity": "warning",
                "component": "secret-age", "secret": "example-api-key"},
        annotations={"summary": "example-api-key has no rotation date"},
        starts_at="2026-03-10T10:00:00Z", ends_at="0001-01-01T00:00:00Z",
    ))


def test_a_page_about_an_open_item_concerns_the_id_the_model_read_in_its_turn(pod) -> None:
    """The stub can only name 12 by reading it out of the turn triage built."""
    result = _triage("9dd4a93b4a18b053")
    assert result.worklist_items == (_ITEM,), (
        f"the page concerns {result.worklist_items}; the turn should have shown item {_ITEM}"
    )


def test_an_id_no_open_item_has_is_dropped(pod) -> None:
    """A guessed id that is not an open item never reaches the relay."""
    pod["override"] = 999
    result = _triage("1c0ffee000000001")
    assert result.worklist_items == (), f"a guessed id survived: {result.worklist_items}"
