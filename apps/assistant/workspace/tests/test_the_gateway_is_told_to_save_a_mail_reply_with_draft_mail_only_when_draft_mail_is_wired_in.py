"""The gateway is told to save a mail reply with draft_mail, only when draft_mail is wired in.

WHAT IT PINS. `workspace.capabilities.render_capabilities()`, the block rendered
into AGENTS.md, and the VM section of it that names the mail box's tools.

WHY IT EXISTS. A model told only "you send no email" can read it as "mail is
the human's job" and refuse to draft a reply it has the tool for, even with
draft_mail in its tool list and a description saying it only saves to
Drafts. The tool is known; the step is not. The line has to follow the wiring, because a line
telling the assistant to draft with a tool it has not got is the opposite lie.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Whether
draft_mail is wired in is given to the renderer as its server list, the
fragment the gateway is configured from. The second case hands the render a
mail server with no draft_mail, as the fragment would be with it taken out.
"""
from __future__ import annotations


import pytest

from apps.assistant.workspace import capabilities



def _vm_paragraph() -> str:
    return next(
        paragraph for paragraph in capabilities.render_capabilities().split("\n\n")
        if paragraph.startswith(capabilities.VM_HEADING)
    )


def test_the_vm_section_makes_drafting_the_next_step_when_draft_mail_is_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """With draft_mail wired in, the assistant is told to save the reply in their Drafts."""
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: (("mail", ("draft_mail", "list_mail", "read_mail")),))
    paragraph = _vm_paragraph()
    assert "save it with draft_mail" in paragraph and "Drafts" in paragraph, (
        f"the gateway is never told to draft the mail itself: {paragraph!r}"
    )
    assert "never tell someone you don't do email" in paragraph


def test_no_drafting_line_when_draft_mail_is_not_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mail server without draft_mail gets no line about drafting."""
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: (("harness-mail", ("list_mail", "read_mail")),))
    assert "draft_mail" not in _vm_paragraph()
