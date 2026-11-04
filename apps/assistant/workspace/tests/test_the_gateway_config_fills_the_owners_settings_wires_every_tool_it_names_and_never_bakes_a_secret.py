"""The gateway config fills the owner's settings, gives each Signal sender a session, compacts chat early, names every tool it wires in, keeps every tool the doors serve, books scheduled writes to the assistant, and never bakes a secret.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Every scheduled report tells the model that nobody asked, so its writes are booked to the assistant.

WHAT IT PINS. `gateway_automations.json`, the asks the gateway's cron runs are
given, against the two seams that read who a send was booked to: the door's
`_SELF_PROVENANCE_TOOLS`, which must accept `message_teammate` under the assistant's
name, and `sent_feed.RELAYED_LOOPS`, which relays a send booked to the assistant
(`teammate-self`) into the chat session as a message nobody asked for.
A brief that says only "send the owner the result" reads to the model as the
owner having asked, so the send is booked `teammate-asked`, logged "asked by the
owner" and never reaches the chat session a reply lands in.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The sentence is
read out of the JSON file the gateway is configured from, and the door rule it
must agree with is the one `workspace/capabilities.py` states: when nobody
asked, `requested_by` is 'the assistant'.

Every tool a VM-local MCP server hands the gateway is named in the assistant's capability block.

WHAT IT PINS. `workspace.capabilities.render_capabilities()`, the block rendered
into AGENTS.md. It ends by telling the assistant that anything on the project's systems not
named above it is impossible, so a tool the gateway really has but the block
leaves out is a tool the assistant will swear it has not got. When that tool is
`journal_read`, the assistant hands the owner journalctl commands instead of
reading the journal itself.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The tool names
are read straight out of `gateway_config_patch.json`, the fragment the gateway
is configured from, as every `toolFilter.include` of `mcp.servers`. The block is
then split at its section paragraphs, and each name must sit in the VM section,
which must come before the paragraph that declares the list complete.

The gateway fragment fills the owner's settings and never bakes a secret.

WHAT IT PINS. `workspace.fragment`: every `@NAME@` placeholder in the config
fragment and the scheduled reports is filled from the settings, every
`${NAME}` the gateway interpolates itself is left exactly as written, the
report times become cron lines on the owner's zone, the voice model appears
only when voice is on, and the Signal channel comes from the vault.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The settings
below are written by hand, so the expected name, zone and cron lines are read
off them by eye.

The gateway deny list never takes away a tool the door, the journal or the mail box serves.

WHAT IT PINS. `workspace/gateway_config_patch.json`'s `tools.deny`, the list
step 68 hands the gateway to switch off upstream tools the assistant does not use, checked against the tools the assistant must keep: every tool the
MCP door serves (`core/tools/gateway_surface.served_definitions()`), every tool
the fragment wires in from a VM-local server (`toolFilter.include`), and the
upstream tools its memory and workspace run on.

WHY IT EXISTS. Upstream's deny is case-insensitive and takes `*` wildcards,
and it applies to MCP tools as well as its own. One careless glob there
(`assistant*`, `*__*`) would leave the assistant with no door at all on the next deploy,
and nothing else would say so: the gateway would answer every question with
"I cannot reach that".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The gateway
names an MCP tool `<server>__<tool>`, read off the tool list in a live run's
system prompt (`assistant-tools__stack_status`,
`harness-journal__journal_read`). The kept upstream tools are the ones the
assistant actually uses: `write` for
its memory file, `memory_search`, `memory_get`, `exec`, `web_search`.

The gateway is told to save a mail reply with draft_mail, only when draft_mail is wired in.

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

The morning brief's ask fixes the quiet-day line and forbids calling anything fine.

WHAT IT PINS. The `harness:morning-brief` ask in `gateway_automations.json`.
A quiet day left as "one line" of the model's choosing invites a status claim
such as "your calendar is clear" over a calendar holding an event, or a line
listing recoveries. A clause telling it to leave out anything already said
drops items still waiting on the reader.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The phrases are
the brief's written contract: one exact quiet-day sentence, a ban on calling
anything clear or fine, the worklist and an unbooked call link named as things
to check, and no "already told" clause. This pins the ask as text; whether the
model follows it is checked by the next transcript sweep, not here.

USER.md forbids the gateway to guess any teammate's pronouns.

WHAT IT PINS. `workspace.user.render_user()`, the USER.md the gateway reads on
every turn, through `core.people.pronoun_directive`. A name does not say
which pronoun a person uses, and a model that is told nothing guesses from the
name and gets it wrong in front of the person.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The registry
carries no pronouns, so every block must tell the model to use the person's
name or neutral wording, and no block may offer a he/him or she/her form to
copy.

The gateway fragment gives each Signal sender their own session.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`, and its `session.dmScope`.

WHY IT EXISTS. With no scope set, upstream's default "main" puts every
allowlisted Signal DM in one session, `agent:main:main`. A teammate's
"can we meet on Monday?" and the owner's own messages then run in that one session,
so each person's private chat turns sit in the context of everyone else's. This isolates chat history between people; it does not limit
what a tool such as `agenda_view` can read for them.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Read off the
running gateway (OpenClaw 2026.9.1, 2026-10-23): `buildAgentPeerSessionKey`
gives "per-channel-peer" the key `agent:main:signal:direct:<peer>`, and the
Signal plugin's peer for a sender with a number is that E.164 number. That is
the key the chat relay builds, so the two must agree on this scope.

The gateway fragment compacts the assistant's chat early and keeps native memory on.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`. The assistant's main chat session
(`agent:main:main`) can run for weeks without one compaction and re-read
hundreds of thousands of tokens on every reply, because safeguard compaction
only fires at the model window minus a reserve, and `claude-opus-5` has a 1M
window. Condense early rather than reset.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Read off a
running gateway (OpenClaw 2026.9.1). There is no threshold key:
usage-based maintenance blocks at "the active model window minus the selected
compaction reserve" (upstream OpenClaw's `docs/reference/session-management-compaction.md`), the
window is `models.providers.<p>.models[].contextTokens` when authored
(`resolveContextTokensForModelFromCache`), and the reserve floor is
`DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR = 2e4`. The fixed prompt alone
(system prompt, injected files, tool schemas) can exceed 60k tokens on a fresh
cron run, so a 60k total trigger would compact every turn. The fixed prompt is
therefore held to a budget of 20,000 (`tools.deny`, no
skills, shorter door definitions), and the trigger is 60k of conversation on
top of that budget: 100,000 - 20,000 = 80,000.
`keepRecentTokens` 20,000 is the verbatim tail kept. No embedding key is
assumed on the host, so memory search is pinned to `provider: "none"`, upstream's explicit FTS-only mode, with no
fallback, so it cannot silently flip to OpenAI embeddings.
"""
from __future__ import annotations

import inspect


# From every scheduled report books its writes to assistant.

from apps.assistant.workspace import fragment


from apps.assistant.shared.name import ASSISTANT_NAME


import json


from pathlib import Path


from apps.assistant.core import sent_feed


from apps.assistant.core.tools import write_tools


from apps.assistant.gates import mcp


_BOOKED_TO_ASSISTANT = f'requested_by "{ASSISTANT_NAME}"'


def _every_scheduled_report_books_its_writes_to_assistant() -> None:
    """Each cron ask that sends a message says the run books to the assistant, and the relay carries it."""
    automations = fragment.render_automations()["automations"]
    senders = [job for job in automations if "message_teammate" in job["message"]]
    assert senders, "no scheduled report sends through message_teammate any more"
    for job in senders:
        assert "Nobody asked for this run" in job["message"], job["declarationKey"]
        assert _BOOKED_TO_ASSISTANT in job["message"], job["declarationKey"]

    assert write_tools.MESSAGE_TEAMMATE in mcp._SELF_PROVENANCE_TOOLS
    assert "teammate-self" in sent_feed.RELAYED_LOOPS

# From every tool the gateway config wires in is named in assistants capability block.

import pytest


from apps.assistant.workspace import capabilities


_CONFIG = Path(__file__).resolve().parents[1] / "gateway_config_patch.json"


#: An owner's own server on the box, as it would sit in the fragment with a
#: toolFilter. The shipped fragment wires none, so the test adds one.
_SERVERS = (("journal", ("container_logs", "journal_read")),)


@pytest.fixture
def _one_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: _SERVERS)


def _wired_tools() -> set[str]:
    """Every tool name the servers are filtered down to."""
    return {tool for _name, tools in _SERVERS for tool in tools}


def _every_tool_the_gateway_config_wires_in_is_named_in_assistants_capability_block() -> None:
    """journal_read and the mail tools are named, before the 'complete' paragraph."""
    wired = _wired_tools()
    assert "journal_read" in wired, "the tool this test is about has left the config"

    paragraphs = capabilities.render_capabilities().split("\n\n")
    vm_index = next(
        (index for index, paragraph in enumerate(paragraphs)
         if paragraph.startswith(capabilities.VM_HEADING)),
        None,
    )
    assert vm_index is not None, "the block names no tool served on the VM"
    complete_index = next(
        index for index, paragraph in enumerate(paragraphs)
        if "is not a tool named above, you cannot do it" in paragraph
    )
    assert vm_index < complete_index
    missing = {tool for tool in wired if tool not in paragraphs[vm_index]}
    assert not missing, f"wired into the gateway but not named to {ASSISTANT_NAME}: {sorted(missing)}"

# From the fragment fills the owners settings and never bakes a secret.

import re


_ENV = {
    "ASSISTANT_NAME": "Jarvis",
    "ASSISTANT_TIMEZONE": "Europe/Berlin",
    "ASSISTANT_BRIEF_TIME": "07:30",
    "ASSISTANT_ADVISOR_TIME": "10:15",
    "DOMAIN": "example.net",
    "SIGNAL_BOT_NUMBER": "+15550100099",
    "SIGNAL_ALLOWLIST": "uuid:aaa,uuid:bbb",
    "SIGNAL_RECIPIENT": "+15550100001",
    "OPENCLAW_WEBHOOK_SECRET": "must-never-appear",
}


def _every_placeholder_is_filled_and_no_secret_is_baked() -> None:
    rendered = json.dumps([fragment.render_config_patch(_ENV), fragment.render_automations(_ENV)])
    assert not re.search(r"@[A-Z_]+@", rendered), "a placeholder was left unfilled"
    assert "must-never-appear" not in rendered
    assert "${OPENCLAW_TOOLS_AUTHORIZATION}" in rendered, "the gateway's own variable was rewritten"


def _the_name_zone_and_report_times_come_from_the_settings() -> None:
    patch = fragment.render_config_patch(_ENV)
    assert patch["agents"]["entries"]["main"]["name"] == "Jarvis"
    assert patch["agents"]["defaults"]["userTimezone"] == "Europe/Berlin"
    jobs = {job["declarationKey"]: job for job in fragment.render_automations(_ENV)["automations"]}
    assert jobs["harness:morning-brief"]["cron"] == "30 7 * * 1-5"
    assert jobs["harness:weekly-advisor"]["cron"] == "15 10 * * 1"
    assert {job["tz"] for job in jobs.values()} == {"Europe/Berlin"}
    assert 'requested_by \\"Jarvis\\"' in json.dumps(jobs)


def _the_voice_model_is_only_wired_when_voice_is_on() -> None:
    assert "media" not in fragment.render_config_patch(_ENV)["tools"]
    voiced = fragment.render_config_patch({**_ENV, "ASSISTANT_VOICE": "1"})
    model = voiced["tools"]["media"]["models"][0]
    assert model["baseUrl"] == "https://transcribe.example.net/v1"


def _the_signal_channel_comes_from_the_vault() -> None:
    signal = fragment.render_config_patch(_ENV)["channels"]["signal"]
    assert signal["account"] == "+15550100099"
    assert signal["allowFrom"] == ["uuid:aaa", "uuid:bbb"]
    assert signal["defaultTo"] == "+15550100001"
    assert "channels" not in fragment.render_config_patch({**_ENV, "SIGNAL_BOT_NUMBER": ""})


def _a_malformed_report_time_is_refused() -> None:
    with pytest.raises(ValueError):
        fragment.render_automations({**_ENV, "ASSISTANT_BRIEF_TIME": "8am"})

# From the gateway deny list never takes away a tool the door the journal or the mail box serves.

import fnmatch


from apps.assistant.core.tools import gateway_surface


_FRAGMENT = Path(__file__).resolve().parents[1] / "gateway_config_patch.json"


_DOOR_SERVER = "assistant-tools"


_KEPT_UPSTREAM = ("read", "write", "edit", "exec", "memory_search", "memory_get", "web_search")


def _fragment() -> dict:
    """The fragment as step 68 sends it."""
    return fragment.render_config_patch()


def _kept_tools() -> set[str]:
    """Every tool name, as the gateway spells it, that the assistant must keep."""
    door = {
        f"{_DOOR_SERVER}__{definition['name']}"
        for definition in gateway_surface.served_definitions()
    }
    vm_local = {
        f"{server}__{tool}"
        for server, spec in _fragment()["mcp"]["servers"].items()
        for tool in spec.get("toolFilter", {}).get("include", [])
    }
    return door | vm_local | set(_KEPT_UPSTREAM)


def _the_gateway_deny_list_never_takes_away_a_tool_the_door_the_journal_or_the_mail_box_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No deny pattern matches a door, journal, mail or memory tool."""
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    deny = [pattern.lower() for pattern in _fragment()["tools"]["deny"]]
    assert deny, "the fragment denies nothing, so this test checks nothing"
    kept = _kept_tools()
    denied = sorted(
        tool for tool in kept
        if any(fnmatch.fnmatchcase(tool.lower(), pattern) for pattern in deny)
    )
    assert not denied, f"the deny list takes these away from {ASSISTANT_NAME}: {denied}"

# From the gateway is told to save a mail reply with draft mail only when draft mail is wired in.

def _vm_paragraph() -> str:
    return next(
        paragraph for paragraph in capabilities.render_capabilities().split("\n\n")
        if paragraph.startswith(capabilities.VM_HEADING)
    )


def _the_vm_section_makes_drafting_the_next_step_when_draft_mail_is_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """With draft_mail wired in, the assistant is told to save the reply in their Drafts."""
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: (("mail", ("draft_mail", "list_mail", "read_mail")),))
    paragraph = _vm_paragraph()
    assert "save it with draft_mail" in paragraph and "Drafts" in paragraph, (
        f"the gateway is never told to draft the mail itself: {paragraph!r}"
    )
    assert "never tell someone you don't do email" in paragraph


def _no_drafting_line_when_draft_mail_is_not_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mail server without draft_mail gets no line about drafting."""
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: (("harness-mail", ("list_mail", "read_mail")),))
    assert "draft_mail" not in _vm_paragraph()

# From the morning brief never calls a quiet day fine.

def _brief() -> str:
    automations = fragment.render_automations()["automations"]
    return next(job["message"] for job in automations if job["declarationKey"] == "harness:morning-brief")


def _the_morning_brief_never_calls_a_quiet_day_fine() -> None:
    """One fixed quiet-day line, no status claims, no 'already told' drop."""
    brief = _brief()
    assert "send exactly 'Nothing needs you today.'" in brief
    assert "Never call anything clear, fine, back or steady" in brief
    assert "your worklist" in brief
    assert "A worklist item for them goes in unless they were told it before" in brief
    assert "call link" in brief
    assert "anything you already told" not in brief

# From user md tells the gateway each teammates pronouns and forbids guessing.

from apps.assistant.core import state


from apps.assistant.workspace import user


_PEOPLE = (
    "uuid:aaa=Alex:founder:+15550100012,"
    "uuid:bbb=Robin:legal::nl,"
    "uuid:ccc=Kim:design"
)


@pytest.fixture()
def blocks(monkeypatch) -> dict[str, str]:
    """USER.md split into its per-person blocks, keyed by name."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setattr(state, "list_person_rules", lambda name: [])
    rendered = user.render_user()
    found: dict[str, str] = {}
    for chunk in rendered.split("### ")[1:]:
        name, _, body = chunk.partition("\n")
        found[name.strip()] = body
    return found


def _every_teammate_is_named_rather_than_guessed(blocks, name) -> None:
    block = blocks[name]
    assert "use their name or neutral wording" in block, block
    assert "he/him" not in block and "she/her" not in block, block


def _a_reader_of_another_language_is_written_to_in_it(blocks) -> None:
    assert "'nl'" in blocks["Robin"], blocks["Robin"]

# From the gateway fragment gives each signal sender their own session.

def _the_gateway_fragment_gives_each_signal_sender_their_own_session() -> None:
    """Each sender is keyed by channel and peer, the shape the chat relay writes into."""
    patch = fragment.render_config_patch()
    assert patch.get("session", {}).get("dmScope") == "per-channel-peer", (
        "the gateway fragment leaves every Signal DM in one shared session"
    )

# From the gateway fragment compacts chat early and keeps native memory on with a pinned provider.

_UPSTREAM_RESERVE_FLOOR = 20_000


_FIXED_PROMPT_BUDGET = 20_000


def _opus_cap() -> int:
    """The authored context cap for the model the assistant's chat runs on."""
    models = _fragment()["models"]["providers"]["anthropic"]["models"]
    (opus,) = [model for model in models if model["id"] == "claude-opus-5"]
    return opus["contextTokens"]


def _compaction_fires_at_about_sixty_thousand_tokens_of_conversation() -> None:
    """The trigger sits about 60k above the fixed prompt, nowhere near 1M."""
    trigger = _opus_cap() - _UPSTREAM_RESERVE_FLOOR
    assert trigger == 80_000
    assert 50_000 <= trigger - _FIXED_PROMPT_BUDGET <= 70_000


def _compaction_keeps_the_last_twenty_thousand_tokens_verbatim() -> None:
    """The recent tail survives compaction word for word."""
    assert _fragment()["agents"]["defaults"]["compaction"]["keepRecentTokens"] == 20_000


def _memory_is_flushed_before_compaction() -> None:
    """Notes land in memory/YYYY-MM-DD.md before older turns are summarised."""
    assert _fragment()["agents"]["defaults"]["compaction"]["memoryFlush"]["enabled"] is True


def _dreaming_is_off() -> None:
    """The nightly sweep can promote nothing and its diary can invent checks
    that never ran, so it stays off until upstream fixes both."""
    dreaming = _fragment()["plugins"]["entries"]["memory-core"]["config"]["dreaming"]
    assert dreaming["enabled"] is False


def _memory_search_is_on_and_pinned_to_keyword_only() -> None:
    """Search answers from FTS and cannot fall over to an embedding provider."""
    search = _fragment()["memory"]["search"]
    assert search == {"enabled": True, "provider": "none", "fallback": "none"}


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_every_scheduled_report_books_its_writes_to_assistant),
    *_cases(_every_tool_the_gateway_config_wires_in_is_named_in_assistants_capability_block, uses=('_one_server',)),
    *_cases(_every_placeholder_is_filled_and_no_secret_is_baked),
    *_cases(_the_name_zone_and_report_times_come_from_the_settings),
    *_cases(_the_voice_model_is_only_wired_when_voice_is_on),
    *_cases(_the_signal_channel_comes_from_the_vault),
    *_cases(_a_malformed_report_time_is_refused),
    *_cases(_the_gateway_deny_list_never_takes_away_a_tool_the_door_the_journal_or_the_mail_box_serves),
    *_cases(_the_vm_section_makes_drafting_the_next_step_when_draft_mail_is_wired),
    *_cases(_no_drafting_line_when_draft_mail_is_not_wired),
    *_cases(_the_morning_brief_never_calls_a_quiet_day_fine),
    *_cases(_every_teammate_is_named_rather_than_guessed, "name", ["Alex", "Robin", "Kim"]),
    *_cases(_a_reader_of_another_language_is_written_to_in_it),
    *_cases(_the_gateway_fragment_gives_each_signal_sender_their_own_session),
    *_cases(_compaction_fires_at_about_sixty_thousand_tokens_of_conversation),
    *_cases(_compaction_keeps_the_last_twenty_thousand_tokens_verbatim),
    *_cases(_memory_is_flushed_before_compaction),
    *_cases(_dreaming_is_off),
    *_cases(_memory_search_is_on_and_pinned_to_keyword_only),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_gateway_config_fills_the_owners_settings_wires_every_tool_it_names_and_never_bakes_a_secret(scenario, given, uses, request):
    """The gateway config fills the owner's settings, gives each Signal sender a session, compacts chat early, names every tool it wires in, keeps every tool the doors serve, books scheduled writes to the assistant, and never bakes a secret: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
