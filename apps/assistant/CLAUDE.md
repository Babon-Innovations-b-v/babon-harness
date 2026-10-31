# apps/assistant/

The assistant: an upstream OpenClaw gateway that holds the Signal conversation, and this package, the door, which triages alerts before they reach a phone and serves the assistant's own tools to the gateway over MCP. `compose.yml` runs both plus signal-cli and, under the `voice` profile, a speech model. Read the overlay closest to the file you touch.

## Do not get wrong

- **The door never reads Signal.** The gateway owns inbound chat. Two consumers of one signal-cli queue lose messages, because a receive is destructive. Do not add an inbound chat route here.
- **A deadman never routes through the door.** Anything that watches the door being down calls `fan_out(..., signal_direct=True)`.
- **No new write tool without a decision.** Every write sits behind its own kill switch, a token and an audit row in `state.assistant_actions`, written before the write is reported done.
- **Never swallow a state or Signal write failure**: propagate it or dead-letter it.
- **Don't retry a beat trigger that timed out on read.** The door is running the pass and no beat route is idempotent.
- **Configuration has three homes**: `.claude/project.json` (repo, people, areas, backlog), `config/harness.env` (settings) and the vault (secrets). The assistant's name is `ASSISTANT_NAME`; never write a name into code or prompts.

## Add a person

Put them in the vault: their Signal UUID in `SIGNAL_ALLOWLIST` (`uuid:<id>`), and `uuid:<id>=Name:role:+number:language` in `SIGNAL_PEOPLE`. The number is optional (leave it empty to never message them), the language defaults to English, the role is free text. The person must message the bot number first, so signal-cli knows their UUID. The next deploy cycle pulls the vault and restarts the door.

## Mute a known-flaky alert

`docker compose exec assistant python3 -c "from apps.assistant.core import state; state.add_suppression(pattern='<alertname>%', reason='known flake', added_by='<you>')"`. Patterns are SQL LIKE. It refuses a pattern that also covers something that paged critical recently; narrow the pattern rather than pass `force=True`.
