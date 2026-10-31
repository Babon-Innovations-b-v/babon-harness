"""`personal_rule` tool, a teammate shapes how the assistant talks to THEM.

The counterpart to `remember_principle`: where a principle is the owner's
global doctrine (applied in every loop, for everyone), a personal rule is
one person's own preference (tone, how much detail, language), and it
applies ONLY when the assistant talks to that person. Crucially it is
self-scoped: the tool always writes/reads/removes the CURRENT sender's
rules, so a teammate can change how the assistant talks to a teammate and nothing else, and
cannot touch the owner's rules or the global doctrine.

Wired in `core.chat` with the sender's name as `person`. Not in the shared
read-only registry.

The self-scoping above holds exactly as far as `person` is trustworthy. In the
pod it is: a Signal message carries a verified sender. The tool
is also served over the MCP door, where `person` is the name the calling model
typed in `requested_by`; the door refuses a name its people registry does not
hold and records every call, so a rule written for the wrong person is bounded
and visible, but it is not impossible there.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: Tier-2 in the chat dispatch (a fault returns as text);
the underlying `state.*_person_rule` writes are Tier-1 (propagate).
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core import state

NAME = "personal_rule"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Add, list or remove a rule for how the person you are talking to wants "
        "to be treated ('keep it short with me'). Only they change their own; a "
        "rule for everyone is remember_principle."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "remove"]},
            "rule": {"type": "string", "description": "The preference as a durable rule."},
            "rule_id": {"type": "integer", "description": "From list."},
        },
        "required": ["action"],
    },
}


def execute(tool_input: dict[str, Any], person: str = "") -> str:
    person = (person or "").strip()
    if not person:
        return "I do not know who you are yet, so I cannot keep a personal rule for you."
    action = str(tool_input.get("action", "")).strip()

    if action == "add":
        rule = str(tool_input.get("rule", "")).strip()
        if not rule:
            return "no rule text given; nothing recorded."
        state.add_person_rule(person, rule)
        return f"recorded your personal rule: {rule}"

    if action == "list":
        rules = state.list_person_rules(person)
        if not rules:
            return f"you have no personal rules set yet, {person}."
        return "your personal rules:\n" + "\n".join(
            f"[{rule['id']}] {rule['text']}" for rule in rules
        )

    if action == "remove":
        try:
            rule_id = int(tool_input.get("rule_id"))
        except (TypeError, ValueError):
            return "remove needs a numeric rule_id (see 'list')."
        removed = state.delete_person_rule(rule_id, person)
        return f"removed rule {rule_id}." if removed else f"no rule {rule_id} of yours to remove."

    return f"unknown action {action!r}; use add, list or remove."
