"""A page never ends on the lead-in of a fix step whose command was stripped.

WHAT IT PINS. Two halves of one road, across their public interfaces. First,
`core.signal_text.strip_markdown`, the last seam before Signal: when it drops a
command for the reader to run, it drops the whole fix step with it, the line
that introduced the command ("To un-stall it:") and the "Then ..." that
continued it, and it never leaves a double blank gap where a line was. Second,
`core.triage.triage`: the alert the model is shown carries no `first_action`
annotation, because that annotation is an ssh command written for a person at
a terminal and the model would write its draft around it.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every draft
below is the shape a held page has before the strip, and the expected text is what a person
reading it would keep: the sentences that say what is wrong, nothing that only
pointed at a command. The chat-shaped case is a plain answer with a list and no
command, and the expected answer is the input unchanged, because the fix may not
touch a message that had nothing stripped.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from apps.assistant.core.signal_text import strip_markdown

_STALL_DRAFT = (
    "harness-github-mail-janitor.timer is stalled. It has no next run scheduled.\n"
    "\n"
    "To un-stall it:\n"
    "ssh deploy@203.0.113.10 'sudo systemctl restart harness-github-mail-janitor.timer'\n"
    "\n"
    "Then confirm the unit has OnActiveSec= so the stall cannot recur."
)

_GAP_DRAFT = (
    "OOM killer fired on the VM around 10:50 UTC. Memory has recovered.\n"
    "\n"
    "sudo dmesg -T | grep -i 'killed process'\n"
    "\n"
    "Cluster pods all look fine."
)

_READ_ONLY_DRAFT = (
    "Repo index build has been failing since 09:21 UTC today.\n"
    "\n"
    "No Loki trace, need the VM log:\n"
    "grep '[graph]' /var/log/harness/auto-deploy.log | tail -20"
)

_CHAT_ANSWER = (
    "Three things landed this morning:\n"
    "the deploy at 09:29\n"
    "the Caddy path rewrite\n"
    "\n"
    "Also, the index caught up at 10:02."
)


def test_a_stripped_command_takes_its_lead_in_and_its_next_step_with_it() -> None:
    """The stall page keeps what is wrong and loses the whole fix step."""
    assert strip_markdown(_STALL_DRAFT) == (
        "harness-github-mail-janitor.timer is stalled. It has no next run scheduled."
    )


def test_a_dropped_line_leaves_one_blank_line_not_two() -> None:
    """The blank lines either side of a dropped command do not both survive."""
    assert strip_markdown(_GAP_DRAFT) == (
        "OOM killer fired on the VM around 10:50 UTC. Memory has recovered.\n"
        "\n"
        "Cluster pods all look fine."
    )


def test_a_read_only_command_line_goes_with_its_lead_in() -> None:
    """grep and tail at the start of a line are commands too."""
    assert strip_markdown(_READ_ONLY_DRAFT) == (
        "Repo index build has been failing since 09:21 UTC today."
    )


def test_a_message_with_nothing_stripped_is_left_alone() -> None:
    """A chat answer with a colon lead-in and an "Also" line keeps both, because
    nothing next to them was a command."""
    assert strip_markdown(_CHAT_ANSWER) == _CHAT_ANSWER


@pytest.fixture()
def shown_to_model(tmp_path, monkeypatch) -> list[str]:
    """Run `triage` with the model replaced by a stub that records the alert it
    was shown and submits the stall draft. Nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools

    seen: list[str] = []
    submit = SimpleNamespace(
        type="tool_use",
        id="submit-1",
        name=tools.SUBMIT_NAME,
        input={"decision": "enrich", "reason": "stalled timer", "signal_draft": _STALL_DRAFT},
    )

    def fake_run(*, messages, **_ignored):
        seen.append(messages[0]["content"])
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    return seen


def test_triage_never_shows_the_model_the_first_action_command(shown_to_model) -> None:
    """The ssh command in `first_action` never reaches the model, the rest of the
    annotations do, and the page that comes back has no dangling lead-in."""
    from apps.assistant.core.triage import Alert, triage

    alert = Alert(
        fingerprint="0ecb7af15224b2ab",
        status="firing",
        labels={"alertname": "VMTimerStalled", "severity": "warning"},
        annotations={
            "summary": "harness-github-mail-janitor.timer has no next elapse",
            "first_action": "ssh deploy@203.0.113.10 'sudo systemctl restart x.timer'",
        },
        starts_at="2026-09-28T14:20:00Z",
        ends_at="0001-01-01T00:00:00Z",
    )
    result = triage(alert)
    shown, _rest = json.JSONDecoder().raw_decode(shown_to_model[0])
    assert "first_action" not in shown["annotations"]
    assert shown["annotations"]["summary"] == alert.annotations["summary"]
    assert "ssh" not in shown_to_model[0]
    assert result.signal_draft is not None
    assert not result.signal_draft.rstrip().endswith(":")
    assert "Then confirm" not in result.signal_draft
