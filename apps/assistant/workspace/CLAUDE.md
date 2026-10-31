# apps/assistant/workspace/

Renders what the gateway is handed: `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md` from the live modules, the config fragment and the scheduled reports. `apply.sh` installs them; the deploy loop calls it.

- **The prose is rendered, never hand-edited.** SOUL.md reads the repository's `.claude/soul.md`; principles and person rules come from the state database.
- `@NAME@` placeholders are filled by `fragment.py`; `${NAME}` is the gateway's own syntax and is left alone, so a secret is never baked into a file.
- **The gateway's heartbeat stays off.** Its default wakes the model on a timer with the whole context, which costs real money for nothing.
- **Reports are never delivered by the gateway.** They leave through `message_teammate`, where the word cap is code.
- A render over the gateway's size cap is refused, not truncated. Compact the principles instead.
- Moving the pinned gateway image means checking the fragment against `openclaw config schema` again.
