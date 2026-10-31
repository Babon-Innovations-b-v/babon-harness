"""Claude call that turns a transcript into meeting minutes.

Loads the minutes template once (lazy) and prompts Claude with strict filling
rules so the output always has the template's shape. Does NOT own the AI-call
bookkeeping: ``dashkit.ai.call_claude`` logs tokens and cost to
``notulen_ai_calls``.

The minutes are written in the language the meeting was held in, so one
deployment serves a team that meets in any language.

Twin declaration: ``apps/notulen/entrypoints/worker.py`` carries its own
prompt and template loader by design (self-contained GPU image). The speaker
paragraph must read the same on both sides; a test pins that.

FAILURE POLICY: Tier-1. A Claude error raises ``RuntimeError`` and
``process_job`` marks the job ``failed``.
"""
from __future__ import annotations

from dashkit.ai import call_claude

from apps.notulen.app.core.publish.github.target_path import target_path
from apps.notulen.app.shared.config import TEMPLATE_PATH

_NOTULEN_TEMPLATE: str = ""


def _load_template() -> str:
    global _NOTULEN_TEMPLATE
    if not _NOTULEN_TEMPLATE:
        if TEMPLATE_PATH.exists():
            _NOTULEN_TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")
        else:
            _NOTULEN_TEMPLATE = (
                "# Meeting: [subject]\n\n"
                "**Date**: YYYY-MM-DD\n"
                "**Attendees**:\n"
                "**Minutes by**:\n\n"
                "## Agenda\n\n1. ...\n\n"
                "## Discussed\n\n### Item 1\n-\n\n"
                "## Action items\n\n"
                "| Action | Who | Deadline |\n|---|---|---|\n| | | |\n\n"
                "## Next meeting\n\n"
                "**Date**:\n**Topics**:\n"
            )
    return _NOTULEN_TEMPLATE


def generate_notulen(
    transcript: str,
    title: str,
    meeting_date: str,
    attendees: list[str],
    job_id: str,
    agenda: str = "",
) -> str:
    """Call Claude to structure the transcript into minutes markdown."""
    template = _load_template()

    agenda_block = ""
    if agenda.strip():
        agenda_block = f"""
AGENDA (given beforehand by the person recording):
{agenda.strip()}

Use this agenda as the structure of the "Discussed" section. Topics discussed
that were not on the agenda go in as extra items."""

    system_prompt = f"""You are a professional minute taker.

Write the minutes of the meeting from the transcript. The transcript carries
timestamps [MM:SS] and speaker labels [SPEAKER_00], [SPEAKER_01] and so on per
block. Different labels are different people. Pauses between blocks mark a
change of topic.

ATTENDEES: {", ".join(attendees)}
Link a speaker label to a name only when the transcript proves it: someone is
addressed by name, introduces themselves, or a name is said back. Without that
evidence keep the label itself everywhere ("Speaker 1", "Speaker 2"), including
the "Who" column of the action items table, and put this line under
**Attendees**: The speakers cannot be identified from the audio. Never guess a
name, and do not do it halfway either: naming half of the bullets and not the
other half is the same mistake.

TEMPLATE:
{template}
{agenda_block}
FILLING RULES:
- Subject: "{title}"
- Date: {meeting_date}
- Attendees: {", ".join(attendees)}
- Minutes by: "Automatic (Whisper + Claude)"
- Write in the language the meeting was held in
- "Discussed": one subsection (### Item N: title) per topic discussed.
  Per item: 2-5 short bullets with the gist of what was said.
  Say who said or proposed something when the transcript shows it.
- "Decisions": list only explicit decisions taken in the meeting (for
  example "We will do X", "Decided to Y"). If there are none, write
  "No explicit decisions taken."
- "Action items": fill the table. Every concrete task or commitment separately.
  Who: the person's name, or "Everyone" / "To be decided".
  Deadline: only when a date or term was named explicitly, otherwise empty.
- "Next meeting": fill in only when it was discussed explicitly.
- Leave out small talk, repetition and remarks without substance.
- Return ONLY the filled-in template, no introduction or closing."""

    result = call_claude(
        system_prompt=system_prompt,
        user_prompt=f"TRANSCRIPT:\n\n{transcript}",
        ai_calls_table="notulen_ai_calls",
        run_id=job_id,
        # One path grammar (target_path.py): the AI-call label and the
        # committed file agree on <YYYY-MM>/<who>/<YYYY-MM-DD>.md.
        doc_path=target_path(meeting_date, title, attendees),
    )

    if "error" in result:
        raise RuntimeError(f"Claude API error: {result.get('detail', result['error'])}")

    return result["content"]
